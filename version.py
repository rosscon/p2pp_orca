__author__ = 'Tom Van den Eede'
__copyright__ = 'Copyright 2018-2022, Palette2 Splicer Post Processing Project'
__credits__ = ['Tom Van den Eede',
               'Tim Brookman'
               ]
__license__ = 'GPLv3'
__maintainer__ = 'Tom Van den Eede'
__email__ = 'P2PP@pandora.be'
__status__ = 'BETA'

releaseinfo = {
    '1.0.0': "Initial fork from P2PP",
    '--- RELEASE INFORMATION': 'END'
}

# general version info
MajorVersion = 9
MinorVersion = 1
Build = 1

Version = "{}.{:02}.{:02}".format(MajorVersion, MinorVersion, Build)

if __name__ == "__main__":
    print(Version)
