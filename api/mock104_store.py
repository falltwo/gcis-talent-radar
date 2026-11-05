"""Durable, cookie-isolated stores for the local 404 employer portal."""
import hashlib
import json
import os
import re
import secrets
import time
from contextlib import contextmanager
from pathlib import Path
from fastapi import HTTPException
from api.recruitment_demo import DemoSessions
from recruitment.service import RecruitmentService

RETENTION_SECONDS=30*86400


class PersistentPortalSessions(DemoSessions):
    def __init__(self,root=None):
        super().__init__()
        self.root=Path(root or os.environ.get('MOCK104_DATA_DIR') or Path(__file__).resolve().parents[1]/'data'/'mock104')
        self.ttl_seconds=RETENTION_SECONDS

    def folder(self,key):
        if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{40,64}',key):raise HTTPException(404,'找不到本機職缺工作階段。')
        return self.root/hashlib.sha256(key.encode()).hexdigest()

    def metadata(self,folder,expires):
        folder.mkdir(parents=True,exist_ok=True)
        temporary=folder/'session.json.tmp'
        temporary.write_text(json.dumps({'expires_at':expires}),encoding='utf-8')
        temporary.replace(folder/'session.json')

    def cleanup(self):
        # Expiry revokes access; never erase a user's database as a side effect of a request.
        for key in [k for k,v in self.sessions.items() if v['expires_at']<=time.time()]:self.sessions.pop(key)

    def start_empty(self):
        with self.lock:
            self.cleanup()
            if len(self.sessions)>=128:raise HTTPException(503,'本機工作階段已達上限。')
            key=secrets.token_urlsafe(32);folder=self.folder(key)
            folder.mkdir(parents=True,exist_ok=False)
            service=RecruitmentService(folder/'jobs.sqlite3');expires=time.time()+self.ttl_seconds
            self.metadata(folder,expires)
            self.sessions[key]={'service':service,'id':None,'expires_at':expires,'folder':folder}
            return key

    @contextmanager
    def session(self,key):
        with self.lock:
            self.cleanup();folder=self.folder(key)
            if key not in self.sessions:
                try:
                    expires=json.loads((folder/'session.json').read_text(encoding='utf-8'))['expires_at']
                    if not isinstance(expires,(int,float)) or expires<=time.time() or not (folder/'jobs.sqlite3').is_file():raise ValueError()
                except (OSError,ValueError,KeyError,TypeError):raise HTTPException(404,'職缺工作階段已到期或不存在。') from None
                self.sessions[key]={'service':RecruitmentService(folder/'jobs.sqlite3'),'id':None,'expires_at':expires,'folder':folder}
            yield self.sessions[key]

    def refresh(self,key):
        with self.session(key) as session:
            session['expires_at']=time.time()+self.ttl_seconds
            self.metadata(session['folder'],session['expires_at'])
