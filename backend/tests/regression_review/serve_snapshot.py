"""Serve actual authoring APIs/UI against a fresh private production snapshot.

python -B tests/regression_review/serve_snapshot.py --source-db /path/source.db --database /tmp/review.db
No lifespan/workers; media files are read-only inputs. Generation/deletion routes
are outside this authoring test environment and cannot call external providers.
"""
import argparse
import os
from pathlib import Path
import re
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[3]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source-db',type=Path,required=True)
    parser.add_argument('--database',type=Path,required=True)
    args=parser.parse_args()
    if args.database.exists() or args.database.resolve()==args.source_db.resolve():
        parser.error('Use a new private destination; existing databases are never overwritten')
    with sqlite3.connect(f'file:{args.source_db.resolve()}?mode=ro',uri=True) as source:
        source.execute('PRAGMA query_only=ON')
        if source.execute("SELECT 1 FROM tasks WHERE status IN ('pending','running','queued') LIMIT 1").fetchone():
            parser.error('The snapshot must have no in-flight tasks')
        with sqlite3.connect(args.database) as destination:source.backup(destination)
        assert source.total_changes==0
    os.environ['DATABASE_URL']='sqlite:///'+str(args.database.resolve())
    sys.path.insert(0,str(ROOT/'backend'))
    from app.main import app
    from starlette.staticfiles import StaticFiles
    from starlette.exceptions import HTTPException
    from starlette.responses import JSONResponse
    import uvicorn

    class SpaFiles(StaticFiles):
        async def get_response(self,path,scope):
            try:return await super().get_response(path,scope)
            except HTTPException as exc:
                if exc.status_code!=404:raise
                return await super().get_response('index.html',scope)

    spa=SpaFiles(directory=ROOT/'frontend/my-app/dist',html=True)
    async def review_app(scope,receive,send):
        path=scope.get('path','');method=scope.get('method','GET')
        if method not in {'GET','HEAD','OPTIONS'}:
            allowed=method=='PATCH' and re.fullmatch(r'/api/(?:audio-events/[^/]+|novels/[^/]+/chapters/[^/]+/shots/(?:batch|[^/]+))',path)
            if not allowed:
                await JSONResponse({'detail':'REVIEW_ENVIRONMENT_AUTHORING_ONLY'},status_code=403)(scope,receive,send)
                return
        await (app if path.startswith('/api') else spa)(scope,receive,send)
    uvicorn.run(review_app,host='127.0.0.1',port=18001,lifespan='off',access_log=False)


if __name__=='__main__':main()
