
#!/bin/zsh

version=$(python3 version.py)
outputfile="~/Desktop/p2pp_orca_${version}.dmg"
rm dist/p2pp.dmg
rm -rf build dist
python3 setup.py py2app
rm -rf dist/p2pp_orca.app/Contents/plugins
cp -r dist/* /Applications/
hdiutil create dist/p2pp_orca.dmg -ov -volname "p2ppOrcaInstaller" -fs HFS+ -srcfolder "dist"
#rm /Users/tomvandeneede/Dropbox/Public/p2pp.dmg
#rm ${outputfile}
hdiutil convert dist/p2pp_orca.dmg -format UDZO -o ${outputfile}

