
__author__ = 'Tom Van den Eede'
__copyright__ = 'Copyright 2018, Palette2 Splicer Post Processing Project'
__credits__ = ['Tom Van den Eede',
               'Tim Brookman'
               ]
__license__ = 'GPL'
__maintainer__ = 'Tom Van den Eede'
__email__ = 'P2PP@pandora.be'

import os
import io
import p2pp.gui as gui
from p2pp.formatnumbers import hexify_float
import p2pp.parameters as parameters
import p2pp.sidewipe as sidewipe
import p2pp.variables as v
from p2pp.gcodeparser import gcode_remove_params, get_gcode_parameter, parse_slic3r_config
from p2pp.omega import header_generate_omega, algorithm_process_material_configuration
from p2pp.logfile import log_warning



def pre_processfile():
    emptygrid = 0
    toolchange = 0
    process = ""
    filament = "->"

    for line  in v.input_gcode:
        line = line.strip()
        if len(line)==0:
            continue


        if line.startswith(";LAYER "):
            if (process!=""):
                if (emptygrid==1) and (toolchange==0) :
                    v.skippable_layer.append(True)
                else:
                    v.skippable_layer.append(False)

            process = int(line[7:])
            emptygrid = 0
            toolchange = 0
            filament = "->"


        if line in ["T0","T1","T2","T3"]:
            filament += "{}->".format(line[1])


        if "CP EMPTY GRID START" in line:
            emptygrid += 1

        if "TOOLCHANGE START" in line:
            toolchange += 1


def optimize_tower_skip(skipmax , layersize):
    v.skippable_layer.reverse()
    skipped = 0.0
    skipped_num = 0
    for i in range(len(v.skippable_layer)):
        if skipped >= skipmax:
            v.skippable_layer[i] = False
        elif v.skippable_layer[i] == True:
            skipped = skipped + layersize
            skipped_num +=1

    v.skippable_layer.reverse()

    if v.skippable_layer[0]==True:
        v.skippable_layer[0]=False
        skipped_num -=1
    if skipped>0:
        log_warning("Total Purge Tower delta : {} Layers or {:-6.2f}mm".format(skipped_num, skipped))




# ################### GCODE PROCESSING ###########################
def gcode_process_toolchange(new_tool, location):
    # some commands are generated at the end to unload filament,
    # they appear as a reload of current filament - messing up things
    if new_tool == v.current_tool:
        return

    location += v.splice_offset

    if new_tool == -1:
        location += v.extra_runout_filament
    else:
        v.palette_inputs_used[new_tool] = True

    length = location - v.previous_toolchange_location

    if v.current_tool != -1:
        v.splice_extruder_position.append(location)
        v.splice_length.append(length)
        v.splice_used_tool.append(v.current_tool)

        if len(v.splice_extruder_position) == 1:
            if v.splice_length[0] < v.min_start_splice_length:
                log_warning("Warning : Short first splice (<{}mm) Length:{:-3.2f}".format(length,
                                                                                          v.min_start_splice_length))

                filamentshortage = v.min_start_splice_length - v.splice_length[0]
                v.filament_short[new_tool] = max(v.filament_short[new_tool], filamentshortage)
        else:
            if v.splice_length[-1] < v.min_splice_length:
                log_warning("Warning: Short splice (<{}mm) Length:{:-3.2f} Layer:{} Input:{}".
                            format(v.min_splice_length, length, v.current_layer, v.current_tool))
                filamentshortage = v.min_splice_length - v.splice_length[-1]
                v.filament_short[new_tool] = max(v.filament_short[new_tool], filamentshortage)

    v.previous_toolchange_location = location
    v.current_tool = new_tool


def gcode_filter_toolchange_block(line):
    # --------------------------------------------------------------
    # Do not perform this part of the GCode for MMU filament unload
    # --------------------------------------------------------------
    discarded_moves = ["E-15.0000",
                       "G1 E10.5000",
                       "G1 E3.0000",
                       "G1 E1.5000"
                       ]

    if line.startswith("G1"):
        for gcode_filter in discarded_moves:
            if gcode_filter in line:         # remove specific MMU2 extruder moves
                return ";--- P2PP removed [Discarded Moves] - "+line
        return gcode_remove_params(line, ["F"])

    if line.startswith("M907"):
        return ";--- P2PP removed [Motor Power Settings] - " + line   # remove motor power instructions

    if line.startswith("M220"):
        return ";--- P2PP removed [Feedrate Overrides] - " + line   # remove feedrate instructions

    if line.startswith("G4 S0"):
        return ";--- P2PP removed [Unneeded Dwelling] - " + line   # remove dwelling instructions

    return line


def coordinate_on_bed(x, y):
    if v.bed_origin_x > x:
        return False
    if x >= v.bed_origin_x + v.bed_size_x:
        return False
    if v.bed_origin_y >= y:
        return False
    if y >= v.bed_origin_y + v.bed_size_y:
        return False
    return True


def coordinate_in_tower(x, y):
    if x < v.wipe_tower_info['minx']:
        return False
    if x > v.wipe_tower_info['maxx']:
        return False
    if y < v.wipe_tower_info['miny']:
        return False
    if y > v.wipe_tower_info['maxy']:
        return False
    return True


def entertower():
    if v.cur_tower_z_delta > 0:
        v.processed_gcode.append("G1 Z{} F10800\n".format(v.current_position_z - v.cur_tower_z_delta))
    if v.accessory_mode and (v.total_material_extruded - v.last_ping_extruder_position) > v.ping_interval:
        v.acc_ping_left = 20
        v.processed_gcode.append(v.acc_first_pause)


def leavetower():
    if v.cur_tower_z_delta > 0:
        v.processed_gcode.append("G1 Z{} F10800\n".format(v.current_position_z))



def moved_in_tower():
    return not coordinate_on_bed(v.current_position_x, v.current_position_y)


def retrocorrect_emptygrid():
    pos = len(v.processed_gcode)-1
    while pos > 0:
        if v.processed_gcode[pos].startswith("M900") or v.processed_gcode[pos].startswith("; CP WIPE TOWER FIRST LAYER BRIM END"):
            return
        if v.processed_gcode[pos].startswith("G1 X"):
            v.processed_gcode[pos] = ";--- P2PP removed [Tower Delta] - {}".format(v.processed_gcode[pos])
        pos = pos - 1


def gcode_parseline(gcode_full_line):

 #   if (len(v.processed_gcode)+1)%10==0:
 #       if v.total_material_extruded>0:
 #           v.processed_gcode.append(";P2PP DEBUG - Filament: {:-8.2f}mm  Tool: {} TDelta: {:-8.2f}mm\n".format(v.total_material_extruded, v.current_tool, v.cur_tower_z_delta,))
    __tower_remove = False

    if not gcode_full_line[0] == ";":
        gcode_full_line = gcode_full_line.split(';')[0]

    gcode_full_line = gcode_full_line.rstrip('\n')

    if gcode_full_line == "":
        v.processed_gcode.append("\n")
        return


    if gcode_full_line.startswith('T'):
        new_tool = int(gcode_full_line[1])
        gcode_process_toolchange(new_tool, v.total_material_extruded)
        v.allow_filament_information_update = True
        v.processed_gcode.append(';--- P2PP removed [Tool Change]' + gcode_full_line + "\n")
        return

    if gcode_full_line[0:4] in ["M104", "M106", "M109", "M140", "M190","M73 "]:
        v.processed_gcode.append(gcode_full_line + "\n")
        return

    if v.side_wipe:
        sidewipe.collect_wipetower_info(gcode_full_line)

        if v.side_wipe_skip:
            v.processed_gcode.append(";--- P2PP removed [Side Wipe] - " + gcode_full_line + "\n")
            return

        if moved_in_tower() and v.side_wipe and not v.side_wipe_skip:
            if not gcode_full_line[0] == ";":
                v.processed_gcode.append(";--- P2PP  removes [Purge Tower] -  " + gcode_full_line + "\n")
            gcode_full_line = gcode_remove_params(gcode_full_line, ["X", "Y"])
            __tower_remove = True

    # Processing of extrusion speed commands
    # ############################################
    if gcode_full_line.startswith("M220"):
        new_feedrate = get_gcode_parameter(gcode_full_line, "S")
        if new_feedrate != "":
            v.current_print_feedrate = new_feedrate / 100

    # Processing of extrusion multiplier commands
    # ############################################
    if gcode_full_line.startswith("M221"):
        new_multiplier = get_gcode_parameter(gcode_full_line, "S")
        if new_multiplier != "":
            v.extrusion_multiplier = new_multiplier / 100

    # processing tower Z delta
    if "CP EMPTY GRID END" in gcode_full_line:
        v.towerskipped = False
        v.empty_grid = False
        leavetower()

    if v.towerskipped:
        v.processed_gcode.append(';--- P2PP removed [Tower Delta] - ' + gcode_full_line + "\n")
        return

    # Processing of print head movements
    #############################################

    if v.empty_grid and (v.wipe_feedrate != 2000):
        gcode_full_line = gcode_remove_params(gcode_full_line, ["F"])

    if gcode_full_line.startswith("G") and not gcode_full_line.startswith("G28"):
        to_x = get_gcode_parameter(gcode_full_line, "X")
        to_y = get_gcode_parameter(gcode_full_line, "Y")
        to_z = get_gcode_parameter(gcode_full_line, "Z")
        to_e = get_gcode_parameter(gcode_full_line, "E")
        prev_x = v.current_position_x
        prev_y = v.current_position_y


        if to_x != "":
            v.previous_position_x = v.current_position_x
            v.current_position_x = float(to_x)
            if v.define_tower:
                v.wipe_tower_info['maxx'] = max(v.wipe_tower_info['maxx'], v.current_position_x)
                v.wipe_tower_info['minx'] = min(v.wipe_tower_info['minx'], v.current_position_x)
        if to_y != "":
            v.previous_position_y = v.current_position_y
            v.current_position_y = float(to_y)
            if v.define_tower:
                v.wipe_tower_info['maxy'] = max(v.wipe_tower_info['maxy'], v.current_position_y)
                v.wipe_tower_info['miny'] = min(v.wipe_tower_info['miny'], v.current_position_y)
        if to_z != "":
            v.previous_position_z = v.current_position_z
            v.current_position_z = float(to_z)

        if coordinate_in_tower(v.current_position_x, v.current_position_y) and v.towerskipped:
            gcode_full_line = gcode_remove_params(gcode_full_line, ["X", "Y"])

        if not coordinate_on_bed(v.current_position_x, v.current_position_y) and coordinate_on_bed(prev_x, prev_y):
            gcode_full_line = ";" + gcode_full_line

    if gcode_full_line.startswith("G1"):


            if to_e != "":

                extruder_movement = float(to_e)
                extruder_movement = extruder_movement * v.extrusion_multiplier * v.extrusion_multiplier_correction

                if  v.acc_ping_left > 0:

                    if v.acc_ping_left >= extruder_movement:
                        v.acc_ping_left -= extruder_movement

                    else:
                        procent = v.acc_ping_left / extruder_movement
                        intermediate_x = v.previous_position_x + (v.current_position_x - v.previous_position_x) * procent
                        intermediate_y = v.previous_position_y + (v.current_position_y - v.previous_position_y) * procent
                        if to_z !="":
                            zmove = "Z{}".format(to_z)
                        else:
                            zmove=""
                        v.processed_gcode.append("G1 X{} Y{} {} E{}\n".format(intermediate_x,intermediate_y, zmove , v.acc_ping_left))
                        extruder_movement -= v.acc_ping_left
                        v.acc_ping_left = 0
                        gcode_full_line = "G1 X{} Y{} E{}\n".format(v.current_position_x,v.current_position_y, extruder_movement)

                    if v.acc_ping_left<=0.5:
                        v.acc_ping_left=0
                        v.processed_gcode.append(v.acc_second_pause)
                        v.ping_interval = v.ping_interval * v.ping_length_multiplier
                        v.ping_interval = min(v.max_ping_interval, v.ping_interval)
                        v.last_ping_extruder_position = v.total_material_extruded
                        v.ping_extruder_position.append(v.last_ping_extruder_position - to_e)



                if v.within_tool_change_block and v.side_wipe:
                        v.side_wipe_length += extruder_movement

                v.total_material_extruded += extruder_movement

                if (v.total_material_extruded - v.last_ping_extruder_position) > v.ping_interval and\
                         v.side_wipe_length == 0 and not  v.accessory_mode:                             #this code is only handled for connected mode
                                                                                                        #accessory mode is handles during the purge tower sequences only
                    v.ping_interval = v.ping_interval * v.ping_length_multiplier
                    v.ping_interval = min(v.max_ping_interval, v.ping_interval)
                    v.last_ping_extruder_position = v.total_material_extruded
                    v.ping_extruder_position.append(v.last_ping_extruder_position)
                    v.processed_gcode.append(";Palette 2 - PING\n")
                    v.processed_gcode.append("G4 S0\n")
                    v.processed_gcode.append("O31 {}\n".format(hexify_float(v.last_ping_extruder_position)))

            if v.within_tool_change_block and v.side_wipe:
                if not __tower_remove:
                    v.processed_gcode.append(';--- P2PP removed [Side Wipe] - ' + gcode_full_line + "\n")
                return

            if not v.within_tool_change_block and v.wipe_retracted:
                sidewipe.unretract()

    # Other configuration information
    # this information should be defined in your Slic3r printer settings, startup GCode
    ###################################################################################
    if gcode_full_line.startswith(";P2PP"):
        parameters.check_config_parameters(gcode_full_line)



        if gcode_full_line.startswith(";P2PP MATERIAL_"):
                algorithm_process_material_configuration(gcode_full_line[15:])


    if gcode_full_line.startswith("M900"):
        k_factor = get_gcode_parameter(gcode_full_line, "K")
        if float(k_factor) > 0:
            sidewipe.create_side_wipe()
            v.within_tool_change_block = False
            v.mmu_unload_remove = False
        if v.reprap_compatible:
            v.processed_gcode.append(';--- P2PP removed [RepRap Processing] -' + gcode_full_line + "\n")
            return

    if gcode_full_line.startswith(";P2PP ENDPURGETOWER"):
        sidewipe.create_side_wipe()
        v.within_tool_change_block = False
        v.mmu_unload_remove = False

    # Next section(s) clean up the GCode generated for the MMU
    # specially the rather violent unload/reload required for the MMU2
    # special processing for side wipes is required in this section
    #################################################################

    if "CP WIPE TOWER FIRST LAYER BRIM START" in gcode_full_line:
        v.define_tower = True

    if "CP WIPE TOWER FIRST LAYER BRIM END" in gcode_full_line:
        v.define_tower = False
        v.wipe_tower_info['minx'] -= 2
        v.wipe_tower_info['miny'] -= 2
        v.wipe_tower_info['maxx'] += 2
        v.wipe_tower_info['maxy'] += 2
        v.side_wipe = not coordinate_on_bed(v.wipetower_posx, v.wipetower_posy)
        v.processed_gcode.append("; TOWER COORDINATES ({:-8.2f},{:-8.2f}) to ({:-8.2f},{:-8.2f})\n".format(
            v.wipe_tower_info['minx'], v.wipe_tower_info['miny'], v.wipe_tower_info['maxx'], v.wipe_tower_info['maxy'],
            v.wipe_tower_info['minx'], v.wipe_tower_info['miny'], v.wipe_tower_info['maxx'], v.wipe_tower_info['maxy']
        ))
        if v.accessory_mode:
            log_warning("ACCESSORY MODE enabled")
            if v.side_wipe:
                log_warning("ACCESSORY MODE: side wipe will be disabled")
                v.side_wipe = False
            grid_drop = False
            for i in range(len(v.skippable_layer)):
                grid_drop = grid_drop or v.skippable_layer[i]
                v.skippable_layer[i] = False
            if grid_drop:
                log_warning("ACCESSORY MODE: asynchronous purge tower will be disabled")


        if v.side_wipe:
            if v.side_wipe_loc=="":
                log_warning("Sidewipe configuration incomplete (SIDEWIPELOC paramter not set.. gcode will not be usable")
            else:
                log_warning("Side wipe enabled on position {} Y{}-{}".format(v.side_wipe_loc, v.sidewipe_miny,v.sidewipe_maxy))

    if "CP EMPTY GRID START" in gcode_full_line:
        v.empty_grid = True

        if v.skippable_layer[v.layer_count] and v.layer_count>1:
            v.cur_tower_z_delta += v.layer_height
            retrocorrect_emptygrid()
            v.towerskipped = True
        else:
            v.current_print_feed = v.wipe_feedrate / 60
            v.processed_gcode.append(";P2PP Set wipe speed to {}mm/s\n".format(v.current_print_feed))
            v.processed_gcode.append("G1 F{}\n".format(v.wipe_feedrate))
            entertower()

    if "TOOLCHANGE START" in gcode_full_line:
        v.allow_filament_information_update = False
        v.within_tool_change_block = True
        sidewipe.sidewipe_toolchange_start()
        entertower()

    if "TOOLCHANGE END" in gcode_full_line:
        leavetower()
        if not v.side_wipe:
            v.within_tool_change_block = False
            v.mmu_unload_remove = False

    if "TOOLCHANGE UNLOAD" in gcode_full_line and not v.side_wipe:
        v.current_print_feed = v.wipe_feedrate / 60
        v.mmu_unload_remove = True
        if v.current_layer != "0":
            v.processed_gcode.append(";P2PP Set wipe speed to {}mm/s\n".format(v.current_print_feed))
            v.processed_gcode.append("G1 F{}\n".format(v.wipe_feedrate))
        else:
            v.processed_gcode.append(";P2PP Set wipe speed to 33.3mm/s\n")
            v.processed_gcode.append("G1 F2000\n")

    if "TOOLCHANGE WIPE" in gcode_full_line:
        v.mmu_unload_remove = False
        if coordinate_on_bed(v.current_position_x, v.current_position_y):
            v.processed_gcode.append("G0 X{} Y{}\n".format(v.current_position_x, v.current_position_y))

        # Layer Information
    if gcode_full_line.startswith(";LAYER "):
        v.current_layer = gcode_full_line[7:]
        v.layer_count+=1
        if v.layer_count==0:
            optimize_tower_skip(v.max_tower_z_delta, v.layer_height)

    if v.mmu_unload_remove:
            v.processed_gcode.append(gcode_filter_toolchange_block(gcode_full_line) + "\n")
            return

    if v.within_tool_change_block:
        v.processed_gcode.append(gcode_filter_toolchange_block(gcode_full_line) + "\n")
        return

    # Catch All
    v.processed_gcode.append(gcode_full_line + "\n")


# Generate the file and glue it all together!
# #####################################################################
def generate(input_file, output_file, printer_profile, splice_offset, silent):
    v.printer_profile_string = printer_profile
    basename = os.path.basename(input_file)
    _taskName = os.path.splitext(basename)[0].replace(" ", "_")
    _taskName = _taskName.replace(".mcf", "")

    v.splice_offset = splice_offset

    try:
        opf = open(input_file, encoding='utf-8')
    except:
        try:
            opf = open(input_file)
        except:
            if v.gui:
                gui.user_error("P2PP - Error Occurred", "Could not read input file\n'{}'".format(input_file))
            else:
                print ("Could not read input file\n'{}".format(input_file))
            return


    print("Reading File")
    v.input_gcode = opf.readlines()

    opf.close()

    print("Analyzing slicer parameters")
    parse_slic3r_config()

    print("Analyzing layers")
    pre_processfile()
    print("Found {} layers in print".format(len(v.skippable_layer)))

    #v.side_wipe = not coordinate_on_bed(v.wipetower_posx, v.wipetower_posy)

    # Process the file
    # #################
    print("Processing File")
    for line in v.input_gcode:
        gcode_parseline(line)

    gcode_process_toolchange(-1, v.total_material_extruded)
    omega_result = header_generate_omega(_taskName)
    header = omega_result['header'] + omega_result['summary'] + omega_result['warnings']

    if not silent:
        if v.gui:
            gui.show_warnings(omega_result['warnings'])
        print (''.join(omega_result['summary']))
        print (''.join(omega_result['warnings']))


    # write the output file
    ######################
    print("Generating output file")
    if not output_file:
        output_file = input_file
    opf = open(output_file, "w")
    if not v.accessory_mode:
        opf.writelines(header)
        opf.write("\n\n--------- START PROCESSED GCODE ----------\n\n")
    if  v.accessory_mode:
        opf.write("M0\n")
        opf.write("T0\n")

    opf.writelines(v.processed_gcode)
    opf.close()

    if v.accessory_mode:
        pre, ext = os.path.splitext(output_file)
        maffile = pre+".maf"
        opf = open(maffile, "w")
        for i in range(len(header)):
            if not header[i].startswith(";"):
                opf.write(header[i])



