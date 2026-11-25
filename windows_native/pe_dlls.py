"""Stage installed runtime dependencies beside the ASCII-path debug executable."""
from pathlib import Path
import json,mmap,os,shutil,struct

def imports(path):
    with Path(path).open('rb') as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as data:
        pe=struct.unpack_from('<I',data,0x3c)[0]
        if data[pe:pe+4]!=b'PE\0\0':raise RuntimeError('Not a Windows PE executable: '+str(path))
        count=struct.unpack_from('<H',data,pe+6)[0];size=struct.unpack_from('<H',data,pe+20)[0];opt=pe+24
        magic=struct.unpack_from('<H',data,opt)[0];dirs=opt+(112 if magic==0x20b else 96)
        sections=[struct.unpack_from('<IIII',data,opt+size+i*40+8) for i in range(count)]
        def offset(rva):
            for vs,va,rs,raw in sections:
                if va<=rva<va+max(vs,rs):return raw+rva-va
            return rva
        def name(rva):
            pos=offset(rva);return data[pos:data.find(b'\0',pos)].decode('ascii')
        result=[];rva=struct.unpack_from('<I',data,dirs+8)[0]
        if rva:
            pos=offset(rva)
            while any(data[pos:pos+20]):
                result.append(name(struct.unpack_from('<I',data,pos+12)[0]));pos+=20
        rva=struct.unpack_from('<I',data,dirs+13*8)[0]
        if rva:
            pos=offset(rva)
            while any(data[pos:pos+32]):
                attr,rva_name=struct.unpack_from('<II',data,pos)
                if not attr&1:raise RuntimeError('Unexpected VA-based delayed import: '+str(path))
                result.append(name(rva_name));pos+=32
        return result

def stage(exe,destination,search):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    lookup={p.name.lower():p for folder in reversed(search) for p in Path(folder).glob('*.dll')}
    system=Path(os.environ['SystemRoot'])/'System32'
    queue=[Path(exe)];checked=set();copied={}
    while queue:
        path=queue.pop();key=path.name.lower()
        if key in checked:continue
        checked.add(key)
        for dll in imports(path):
            key=dll.lower()
            if key in lookup:
                src=lookup[key];dst=destination/src.name
                if key not in copied:
                    if not dst.exists() or (dst.stat().st_size,dst.stat().st_mtime_ns)!=(src.stat().st_size,src.stat().st_mtime_ns):
                        shutil.copy2(src,dst)
                    copied[key]=str(src);queue.append(dst)
            elif not ((system/dll).exists() or key.startswith(('api-ms-win-','ext-ms-win-'))):
                raise RuntimeError('Missing installed dependency '+dll+' imported by '+path.name+'. Check MSYS2 UCRT64 dependencies.')
    (destination/'runtime-dependencies.json').write_text(json.dumps(copied,indent=2)+'\n')
    return len(copied)
