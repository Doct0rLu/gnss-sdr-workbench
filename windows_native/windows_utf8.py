from pathlib import Path
import ctypes,struct
from ctypes import wintypes as W
MANIFEST=b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
 <assemblyIdentity version="1.0.0.0" processorArchitecture="amd64" name="GNSSSDR.Native.UTF8" type="win32"/>
 <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"><security><requestedPrivileges>
  <requestedExecutionLevel level="asInvoker" uiAccess="false"/>
 </requestedPrivileges></security></trustInfo>
 <application xmlns="urn:schemas-microsoft-com:asm.v3"><windowsSettings>
  <activeCodePage xmlns="http://schemas.microsoft.com/SMI/2019/WindowsSettings">UTF-8</activeCodePage>
 </windowsSettings></application>
</assembly>'''

def embed_manifest(exe,source):
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.BeginUpdateResourceW.argtypes=[W.LPCWSTR,W.BOOL];api.BeginUpdateResourceW.restype=W.HANDLE
    api.UpdateResourceW.argtypes=[W.HANDLE,ctypes.c_void_p,ctypes.c_void_p,W.WORD,ctypes.c_void_p,W.DWORD]
    api.UpdateResourceW.restype=W.BOOL
    api.EndUpdateResourceW.argtypes=[W.HANDLE,W.BOOL];api.EndUpdateResourceW.restype=W.BOOL
    handle=api.BeginUpdateResourceW(str(exe),False)
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    data=ctypes.create_string_buffer(MANIFEST)
    if not api.UpdateResourceW(handle,ctypes.c_void_p(24),ctypes.c_void_p(1),0,data,len(MANIFEST)):
        error=ctypes.get_last_error();api.EndUpdateResourceW(handle,True);raise ctypes.WinError(error)
    if not api.EndUpdateResourceW(handle,False):raise ctypes.WinError(ctypes.get_last_error())
    # The Windows resource updater discards the MinGW COFF symbol/string-table
    # overlay. Restore it and its file pointer: GDB/BFD needs it to resolve the
    # long DWARF section names, although the Windows loader does not.
    with source.open('rb') as src:
        src.seek(60);pe=struct.unpack('<I',src.read(4))[0]
        src.seek(pe+12);offset,count=struct.unpack('<II',src.read(8))
        if offset and count:
            src.seek(offset);symbols=src.read()
            with exe.open('r+b') as dst:
                dst.seek(0,2);new_offset=dst.tell();dst.write(symbols)
                dst.seek(60);target_pe=struct.unpack('<I',dst.read(4))[0]
                dst.seek(target_pe+12);dst.write(struct.pack('<II',new_offset,count))
