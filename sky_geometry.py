"""Reference sky angles for M1 GPS and BeiDou MEO/IGSO recordings."""
import datetime as dt
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import struct
import xml.etree.ElementTree as ET


@lru_cache(maxsize=8)
def _orbits(file, size, modified, digest):
    if size > 64_000_000:
        return {}
    data = file.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        return {}
    lines = data.decode('ascii').splitlines()
    if not lines or not lines[0].lstrip().startswith('3.'):
        return {}
    rows = {}
    for n, line in enumerate(lines):
        if line[:1] not in ('G', 'C') or not line[1:3].isdigit():
            continue
        try:
            prn = int(line[1:3])
            if line[0]=='C' and (prn<=5 or prn>=59):
                continue  # BeiDou GEO uses a different orbit transformation.
            epoch = dt.datetime(*map(int,line[4:23].split()))
            values = [[float(row[i:i+19].replace('D','E')) if row[i:i+19].strip() else 0.
                       for i in (4,23,42,61)] for row in lines[n+1:n+8]]
            if len(values)==7 and values[5][1]==0:
                rows.setdefault((line[0],prn),[]).append((epoch,values))
        except (ValueError, IndexError):
            continue
    return rows


def _satellite(system, epoch, orbit, adot=0., ndot=0.):
    # Broadcast Keplerian model, time within the system week (GPS or BDT).
    _, crs, dn, mean = orbit[0]
    cuc, ecc, cus, sqrt_a = orbit[1]
    toe, cic, omega0, cis = orbit[2]
    inc0, crc, perigee, node_rate = orbit[3]
    if not 0 < sqrt_a or not 0 <= ecc < 1:
        raise ValueError('Invalid broadcast orbit')
    sow = (epoch-dt.datetime(1980,1,6)).total_seconds()%604800
    tk = (sow-toe+302400)%604800-302400
    gm, spin = (3.986005e14,7.2921151467e-5) if system=='G' else (3.986004418e14,7.292115e-5)
    m = mean + (math.sqrt(gm)/sqrt_a**3 + dn + .5*ndot*tk)*tk
    e = m
    for _ in range(8):
        e -= (e-ecc*math.sin(e)-m)/(1-ecc*math.cos(e))
    phi = math.atan2(math.sqrt(1-ecc*ecc)*math.sin(e),math.cos(e)-ecc)+perigee
    s,c = math.sin(2*phi),math.cos(2*phi)
    u = phi+cus*s+cuc*c
    radius = (sqrt_a**2+adot*tk)*(1-ecc*math.cos(e))+crs*s+crc*c
    inc = inc0 + orbit[4][0]*tk + cis*s+cic*c
    node = omega0 + (node_rate-spin)*tk-spin*toe
    x,y = radius*math.cos(u),radius*math.sin(u)
    return x*math.cos(node)-y*math.cos(inc)*math.sin(node), x*math.sin(node)+y*math.cos(inc)*math.cos(node), y*math.sin(inc)


def angles(sat, rx, lat, lon, label):
    dx,dy,dz = (a-b for a,b in zip(sat,rx))
    along = dx*math.cos(lon)+dy*math.sin(lon)
    east = -dx*math.sin(lon)+dy*math.cos(lon)
    north = -along*math.sin(lat)+dz*math.cos(lat)
    up = along*math.cos(lat)+dz*math.sin(lat)
    return dict(azimuth=math.degrees(math.atan2(east,north))%360,
                elevation=math.degrees(math.atan2(up,math.hypot(east,north))),geometry=label)


@lru_cache(maxsize=32)
def _xml_orbits(file,size,modified):
    if size>4_000_000:return {}
    return {int(row.findtext('PRN')):{e.tag:float(e.text) for e in row}
            for row in ET.parse(file).findall('.//item/second')}


def decoded_angles(path, utc, fix, satellites):
    if not dt.datetime(2017,1,1)<=utc<dt.datetime(2027,1,1):return {}
    lat,lon=map(math.radians,(fix['lat'],fix['lon']))
    n=6378137/math.sqrt(1-0.00669437999014*math.sin(lat)**2)
    h=fix['height']
    rx=((n+h)*math.cos(lat)*math.cos(lon),(n+h)*math.cos(lat)*math.sin(lon),
        (n*(1-0.00669437999014)+h)*math.sin(lat))
    result={}
    for system,prn in satellites:
        if system not in ('G','C'):continue
        file=path/('gps_ephemeris.xml' if system=='G' else 'bds_cnav1_ephemeris.xml')
        try:
            st=file.stat()
            v=_xml_orbits(file,st.st_size,st.st_mtime_ns)[prn]
            if v.get('SV_health',v.get('hs',0)) or (system=='C' and v['sat_type'] not in (2,3)):continue
            epoch=utc+dt.timedelta(seconds=18 if system=='G' else 4)
            start=dt.datetime(1980,1,6) if system=='G' else dt.datetime(2006,1,1)
            elapsed=(epoch-start).total_seconds()
            week=int(v['WN'])
            if system=='G':week+=round((elapsed/604800-week)/1024)*1024
            if abs(elapsed-(week*604800+v['toe']))>7200:continue
            orbit=[[0,v['Crs'],v['delta_n'],v['M_0']],
                   [v['Cuc'],v['ecc'],v['Cus'],v['sqrtA'] if system=='G' else math.sqrt(v['A0'])],
                   [v['toe'],v['Cic'],v['OMEGA_0'],v['Cis']],[v['i_0'],v['Crc'],v['omega'],v['OMEGAdot']],[v['idot']]]
            result[system,prn]=angles(_satellite(system,epoch,orbit,v.get('Adot',0),v.get('delta_ndot',0)),rx,lat,lon,'已解星历回算')
        except (OSError,KeyError,TypeError,ValueError,ET.ParseError):
            continue
    return result


def reference_angles(iq, t, satellites):
    sidecar = Path(str(iq)+'.json')
    if not sidecar.is_file() or sidecar.stat().st_size > 2_000_000:
        return {}
    try:
        meta = json.loads(sidecar.read_text(encoding='utf-8-sig'))
        cfg, traj, nav = meta['config'],meta['receiver_trajectory'],meta['nav']
        if meta['bytes']!=iq.stat().st_size or traj['frame']!='WGS84 ECEF' or traj['interval_ms']!=1:
            return {}
        utc = dt.datetime.fromisoformat(cfg['start_utc']) + dt.timedelta(seconds=t)
        # GPS-UTC is 18 s and BDT-UTC is 4 s for the supported M1 scenario dates.
        if not dt.datetime(2017,1,1)<=utc<dt.datetime(2027,1,1):
            return {}
        ephfile = Path(nav['path'])
        if not ephfile.is_file():
            ephfile = iq.parent/'Windows'/'M1GNSSStudio'/'demos'/ephfile.name
        st = ephfile.stat()
        catalog = _orbits(ephfile,st.st_size,st.st_mtime_ns,nav['sha256'])
        index = round(t*1000)
        if not 0 <= index < traj['epochs']:
            return {}
        plan = iq.parent/Path(traj['file']).name
        if plan.stat().st_size != traj['epochs']*48:
            return {}
        with plan.open('rb') as f:
            f.seek(index*48)
            rx = struct.unpack('<3d',f.read(24))
        lon = math.atan2(rx[1],rx[0])
        horizontal = math.hypot(*rx[:2])
        lat = math.atan2(rx[2],horizontal)
        for _ in range(5):
            normal = 6378137/math.sqrt(1-0.00669437999014*math.sin(lat)**2)
            lat = math.atan2(rx[2]+0.00669437999014*normal*math.sin(lat),horizontal)
        result = {}
        for system,prn in satellites:
            records = catalog.get((system,prn))
            if not records:continue
            epoch = utc+dt.timedelta(seconds=18 if system=='G' else 4)
            toc,orbit = min(records,key=lambda rec:abs((epoch-rec[0]).total_seconds()))
            if abs((epoch-toc).total_seconds())>7200:continue
            result[system,prn] = angles(_satellite(system,epoch,orbit),rx,lat,lon,'M1 参考')
        return result
    except (OSError, KeyError, ValueError, IndexError, TypeError, struct.error, OverflowError):
        return {}
