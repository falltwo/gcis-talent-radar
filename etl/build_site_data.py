"""Offline rebuild of the site's three JSON artifacts, also called by daily_refresh."""
import json
import os
import tempfile
from pathlib import Path

from config import BASE_DIR
from etl.build_district_stats import build as stats
from etl.build_gcis_district_activity import build as activity
from etl.build_district_talent import build as talent

OUTPUT = BASE_DIR/'ui/static'
BUILDERS = {'district-stats.json':stats, 'gcis-district-activity.json':activity, 'district-talent.json':talent}


def replace_bytes(path, content):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='wb',dir=path.parent,delete=False) as handle:
            temporary=Path(handle.name);handle.write(content)
        os.replace(temporary,path)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)


def write_artifact(path, data):
    content=json.dumps(data,ensure_ascii=False,indent=1,allow_nan=False)+'\n'
    replace_bytes(path,content.encode('utf-8'))


def refresh(output_dir=None):
    output=Path(output_dir or OUTPUT)
    # Build and serialize every artifact before replacing any current result.
    artifacts={name:builder() for name,builder in BUILDERS.items()}
    for data in artifacts.values():json.dumps(data,allow_nan=False)
    previous={name:(output/name).read_bytes() if (output/name).exists() else None for name in artifacts}
    written=[]
    try:
        for name,data in artifacts.items():
            write_artifact(output/name,data);written.append(name)
    except OSError:
        for name in reversed(written):
            if previous[name] is None:(output/name).unlink(missing_ok=True)
            else:replace_bytes(output/name,previous[name])
        raise
    return {'artifacts':list(artifacts),
            'gcis_window':artifacts['gcis-district-activity.json'].get('window'),
            'gcis_missing_months':artifacts['gcis-district-activity.json'].get('missing_months'),
            'jobs_snapshot':artifacts['district-stats.json'].get('jobs',{}).get('snapshot_date'),
            'academic_year':artifacts['district-talent.json'].get('academic_year')}


if __name__ == '__main__':
    print(json.dumps(refresh(),ensure_ascii=False,indent=2))
