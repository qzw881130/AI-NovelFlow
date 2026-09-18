"""Private DB, storage and real workers for approved R2 generation evidence.

Usage: python -B tests/regression_r2/serve_execution.py --source-db SOURCE --database NEW_DB --storage-root NEW_DIR --evidence-dir EXISTING_DIR [--seed-voice|--seed-f07]
The source DB is backed up read-only; accepted asset references are copied as
input bytes. No old Source/Log/seal/path records are rewritten or re-signed.
"""
import argparse,hashlib,json,os,sqlite3,sys
from pathlib import Path
import shutil
ROOT=Path(__file__).resolve().parents[3];BACKEND=ROOT/'backend'


def file_hashes(path):
    result={}
    for suffix in ('','-wal','-shm'):
        target=Path(str(path)+suffix)
        if target.is_file():result[target.name]=hashlib.sha256(target.read_bytes()).hexdigest()
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source-db',type=Path,required=True)
    parser.add_argument('--database',type=Path,required=True);parser.add_argument('--storage-root',type=Path,required=True)
    parser.add_argument('--evidence-dir',type=Path,required=True);parser.add_argument('--seed-voice',action='store_true')
    parser.add_argument('--seed-f07',action='store_true')
    parser.add_argument('--port',type=int,default=18001);args=parser.parse_args()
    production_root=(BACKEND/'user_story').resolve();storage=args.storage_root.resolve();database=args.database.resolve()
    if not args.source_db.is_file() or not args.evidence_dir.is_dir():parser.error('Source DB and evidence parent must exist')
    if args.database.exists() or args.storage_root.exists() or (args.evidence_dir/'execution-context.json').exists():
        parser.error('Use new DB, storage and evidence destinations; do not overwrite evidence')
    if (storage==production_root or production_root in storage.parents or storage in production_root.parents
            or database==args.source_db.resolve() or production_root in database.parents):
        parser.error('Private DB and storage must be isolated from source and production storage')
    source_hashes=file_hashes(args.source_db)
    with sqlite3.connect(f'file:{args.source_db.resolve()}?mode=ro',uri=True) as source:
        source.row_factory=sqlite3.Row;source.execute('PRAGMA query_only=ON')
        if source.execute("SELECT 1 FROM tasks WHERE status IN ('pending','running','queued') LIMIT 1").fetchone():
            raise RuntimeError('SOURCE_DATABASE_HAS_ACTIVE_TASKS')
        with sqlite3.connect(args.database) as destination:source.backup(destination)
        refs=[]
        for table in ('characters','scenes','props'):
            for row in source.execute(f'SELECT * FROM {table} WHERE novel_id=?',('31295501-a729-4fe7-aa76-a98c06121b98',)):
                for key in ('image_url','reference_audio_url'):
                    if key in row.keys() and row[key] and row[key].startswith('/api/files/'):refs.append(row[key])
    args.storage_root.mkdir(parents=True)
    copies=[]
    for url in dict.fromkeys(refs):
        relative=url.removeprefix('/api/files/');origin=BACKEND/'user_story'/relative;target=args.storage_root/relative
        if not origin.is_file():raise RuntimeError('SOURCE_ASSET_MISSING: '+str(origin))
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(origin,target)
        digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
        if digest(origin)!=digest(target):raise RuntimeError('SOURCE_ASSET_COPY_CHANGED: '+str(origin))
        copies.append({'url':url,'sha256':digest(target),'source':str(origin),'copy':str(target)})
    if file_hashes(args.source_db)!=source_hashes:raise RuntimeError('SOURCE_DATABASE_CHANGED_DURING_BACKUP')
    os.environ['DATABASE_URL']='sqlite:///'+str(database)
    os.environ['NOVELFLOW_STORAGE_ROOT']=str(storage)
    sys.path[:0]=[str(BACKEND),str(BACKEND/'tests')]
    from app.core.database import SessionLocal,engine
    from app.services.chapter_shot_split_schema import upgrade as upgrade_split
    upgrade_split(engine)
    context={'database':str(args.database.resolve()),'storageRoot':str(args.storage_root.resolve()),'port':args.port,'inputCopies':copies,
             'sourceDatabase':str(args.source_db.resolve()),'sourceDatabaseHashes':source_hashes,
             'f44':{'novelId':'31295501-a729-4fe7-aa76-a98c06121b98','chapterId':'49a0e2aa-b633-44de-adb0-f2573f790e97','shotId':'edebac68-4f2a-4213-b42d-55425a968bbf'}}
    if args.seed_voice:
        from regression_r2.voice_fixture import seed
        with SessionLocal() as db:context['f17']=seed(db)
    if args.seed_f07:
        from regression_r2.f07_fixture import seed
        with SessionLocal() as db:context['f07']=seed(db,storage)
    (args.evidence_dir/'execution-context.json').write_text(json.dumps(context,ensure_ascii=False,indent=2))
    from app.main import app
    from starlette.staticfiles import StaticFiles
    from starlette.exceptions import HTTPException
    from starlette.responses import JSONResponse
    from contextlib import asynccontextmanager
    import uvicorn
    class SpaFiles(StaticFiles):
        async def get_response(self,path,scope):
            try:return await super().get_response(path,scope)
            except HTTPException as exc:
                if exc.status_code!=404:raise
                return await super().get_response('index.html',scope)
    spa=SpaFiles(directory=ROOT/'frontend/my-app/dist',html=True)
    async def execution_app(scope,receive,send):
        if scope['type']=='lifespan':return await app(scope,receive,send)
        if scope.get('method')=='DELETE':
            return await JSONResponse({'detail':'R2_EXECUTION_NO_DELETE'},status_code=403)(scope,receive,send)
        await (app if scope.get('path','').startswith('/api') else spa)(scope,receive,send)
    uvicorn.run(execution_app,host='127.0.0.1',port=args.port,access_log=False)


if __name__=='__main__':main()
