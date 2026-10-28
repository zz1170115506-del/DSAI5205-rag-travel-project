"""导出本地源码与测试证据，排除环境、密钥和临时文件。"""
import argparse,hashlib,json,subprocess,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
EXCLUDED={'.git','.venv','__pycache__','.pytest_cache','node_modules','work','outputs'}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('destination',type=Path)
    args=parser.parse_args()
    raw=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT)
    names=sorted(set(raw.decode().split('\0'))-{''})
    files=[]
    for name in names:
        path=Path(name)
        if any(part in EXCLUDED for part in path.parts):continue
        if path.name.startswith('.env') and path.name!='.env.example':continue
        if path.suffix in {'.pyc','.log'} or name=='source-manifest.json':continue
        if (ROOT/path).is_symlink():raise SystemExit('拒绝打包符号链接：'+name)
        if (ROOT/path).is_file():files.append(name)
    manifest={name:{'sha256':hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),'bytes':(ROOT/name).stat().st_size} for name in files}
    (ROOT/'source-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    args.destination.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(args.destination,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in [*files,'source-manifest.json']:archive.write(ROOT/name,'hk-travel-assistant/'+name)
    with zipfile.ZipFile(args.destination) as archive:
        assert archive.testzip() is None
        for name,info in manifest.items():assert hashlib.sha256(archive.read('hk-travel-assistant/'+name)).hexdigest()==info['sha256']
    result={'file_count':len(files)+1,'zip_sha256':hashlib.sha256(args.destination.read_bytes()).hexdigest(),'zip_bytes':args.destination.stat().st_size,'manifest_verified':True,'secrets_and_environments_excluded':True}
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
