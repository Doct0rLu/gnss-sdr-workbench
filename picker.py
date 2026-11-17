"""Windows common file dialog in an isolated process; no GUI toolkit required."""
import ctypes as c,json,sys
from ctypes import wintypes as w
class OPENFILENAME(c.Structure):
    _fields_=[('lStructSize',w.DWORD),('hwndOwner',w.HWND),('hInstance',w.HINSTANCE),('lpstrFilter',w.LPCWSTR),('lpstrCustomFilter',w.LPWSTR),('nMaxCustFilter',w.DWORD),('nFilterIndex',w.DWORD),('lpstrFile',w.LPWSTR),('nMaxFile',w.DWORD),('lpstrFileTitle',w.LPWSTR),('nMaxFileTitle',w.DWORD),('lpstrInitialDir',w.LPCWSTR),('lpstrTitle',w.LPCWSTR),('Flags',w.DWORD),('nFileOffset',w.WORD),('nFileExtension',w.WORD),('lpstrDefExt',w.LPCWSTR),('lCustData',c.c_ssize_t),('lpfnHook',c.c_void_p),('lpTemplateName',w.LPCWSTR),('pvReserved',c.c_void_p),('dwReserved',w.DWORD),('FlagsEx',w.DWORD)]
kind=sys.argv[1];buf=c.create_unicode_buffer(32768)
filters={'iq':'IQ 文件\0*.bin;*.iq;*.iq8;*.dat\0所有文件\0*.*\0\0','exe':'接收机\0*.exe\0\0','config':'接收机配置\0*.conf\0所有文件\0*.*\0\0'}
dialog=OPENFILENAME();dialog.lStructSize=c.sizeof(dialog);dialog.lpstrFile=c.cast(buf,w.LPWSTR);dialog.nMaxFile=len(buf);dialog.lpstrFilter=filters[kind];dialog.nFilterIndex=1;dialog.lpstrTitle={'iq':'选择 IQ 文件','exe':'选择接收机','config':'打开配置'}[kind];dialog.Flags=0x80000|0x1000|0x800|0x8
api=c.WinDLL('comdlg32');api.GetOpenFileNameW.argtypes=[c.POINTER(OPENFILENAME)];api.GetOpenFileNameW.restype=w.BOOL
ok=api.GetOpenFileNameW(c.byref(dialog))
if not ok and api.CommDlgExtendedError():raise OSError('Windows file dialog failed')
print(json.dumps({'path':buf.value if ok else ''},ensure_ascii=True))
