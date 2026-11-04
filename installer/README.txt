FDM overhangs (FDMOverhang) - Fusion 360 add-in
===============================================

Paints over the model what will need support, like a slicer's support
preview: faces pointing down at less than the limit angle from the
horizontal in red and orange, and what rests on the bed in green.
The design is not modified.

Install (Windows)
-----------------
1. Unzip the whole zip into any folder.
2. Double-click instalar.bat.
3. In Fusion 360: Utilities > Add-Ins (Shift+S) > FDMOverhang > Run,
   and tick "Run on Startup" so it always starts.

The buttons are in DESIGN > INSPECT > FDM overhangs and Wall thickness.
The add-in is in Spanish if Fusion is in Spanish, and in English otherwise.

To update to a new version, run its instalar.bat: the last dialog values
are kept. If Fusion is open, stop the add-in and run it again.

Uninstall
---------
Stop the add-in in Fusion and double-click desinstalar.bat.

Mac
---
Copy the FDMOverhang folder to
~/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns/

More information
----------------
FDMOverhang/README.en.md, or the repository:
https://github.com/buho29/fdm-overhang
