"""Generate and exercise dependency-free local CRUD systems. SPDX-License-Identifier: MIT.

The version 1 input describes named SQLite resources and typed fields. The fixed
runtime accepts HTTP over a user-private Unix socket. Generation can verify its
own freshly generated source in a disposable subprocess before publication.
It never accepts application code, deploys, or certifies production readiness.
"""

import contextlib
import hashlib
import http.client
import os
import pathlib
import re
import socket
import subprocess
import sys
import tempfile
import time

from .factory import FactoryError, _exact, _identifier, _list, _revision, plan_factory
from .orchestration import _open_private, _safe_directory, canonical, load_json, sha


_NAME = re.compile(r'[a-z][a-z0-9_]{0,39}')
_FIELD_TYPES = {'text': 'TEXT', 'integer': 'INTEGER', 'boolean': 'INTEGER'}
MAX_TEXT = 1024
MAX_BODY = 128 * 1024

# The generated program is standalone. Its only substitutions are a SHA-256
# digest and bounded constants; the user specification remains data.
_RUNTIME = '''#!/usr/bin/env python3
"""Generated local HTTP application. Python standard library only."""

import argparse
import contextlib
import hashlib
import http.server
import json
import os
import pathlib
import re
import signal
import socketserver
import sqlite3
import stat

CONFIG_SHA256 = '@CONFIG_SHA256@'
SCHEMA_SHA256 = '@SCHEMA_SHA256@'
MAX_TEXT = @MAX_TEXT@
MAX_BODY = @MAX_BODY@
MAX_ID = (1 << 63) - 1


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def reject_constant(_):
    raise ValueError('nonfinite JSON number')


def read_bound(name, expected):
    path = pathlib.Path(__file__).absolute().with_name(name)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('unsafe generated configuration')
        raw = stream.read(256 * 1024 + 1)
    if len(raw) > 256 * 1024 or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('changed generated configuration')
    return raw


def state_directory(value):
    path = pathlib.Path(value).absolute()
    if '..' in path.parts:
        raise ValueError('noncanonical state directory')
    for ancestor in [path, *path.parents]:
        marker = ancestor / '.git'
        if ancestor.is_symlink() or marker.is_file() or (marker / 'HEAD').is_file():
            raise ValueError('state directory must be outside Git and symlink-free')
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('state directory must be user-private')
    return path


def quoted(name):
    return '"' + name + '"'


def initialize_database(path, schema, identity):
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or info.st_mode & 0o077):
            raise ValueError('unsafe SQLite file')
    finally:
        os.close(fd)
    with contextlib.closing(sqlite3.connect(path)) as db:
        with db:
            db.execute('BEGIN IMMEDIATE')
            found = db.execute("SELECT name FROM sqlite_schema WHERE type = 'table'").fetchall()
            if not found:
                for statement in schema.splitlines():
                    db.execute(statement)
                db.execute('INSERT INTO "__factory" (identity) VALUES (?)', (identity,))
            elif ('__factory',) not in found or db.execute(
                    'SELECT identity FROM "__factory"').fetchall() != [(identity,)]:
                raise ValueError('database belongs to a different project or schema')


class LocalServer(socketserver.UnixStreamServer):
    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(3.0)
        return connection, address


def handler(resources, db_path, project):
    routes = {row['name']: row['fields'] for row in resources}

    class API(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, status, payload):
            raw = json.dumps(payload, ensure_ascii=False, allow_nan=False,
                             separators=(',', ':')).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(raw)

        def read_values(self, fields):
            lengths = self.headers.get_all('Content-Length') or []
            if (self.headers.get_all('Transfer-Encoding') or len(lengths) != 1
                    or not re.fullmatch(r'[0-9]{1,6}', lengths[0])):
                raise ValueError('valid content length required')
            length = int(lengths[0])
            if length > MAX_BODY:
                raise OverflowError('request too large')
            if (not self.headers.get_all('Content-Type')
                    or len(self.headers.get_all('Content-Type')) != 1
                    or self.headers.get_content_type() != 'application/json'):
                raise TypeError('JSON content type required')
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError('incomplete body')
            data = json.loads(raw.decode('utf-8'), object_pairs_hook=strict_object,
                              parse_constant=reject_constant)
            if not isinstance(data, dict) or set(data) - {field['name'] for field in fields}:
                raise ValueError('unknown field or malformed object')
            values = []
            for field in fields:
                value = data.get(field['name'])
                kind = field['type']
                if value is None:
                    if field['required']:
                        raise ValueError('required field missing')
                elif kind == 'text':
                    if type(value) is not str or len(value.encode('utf-8')) > MAX_TEXT:
                        raise ValueError('invalid text field')
                elif kind == 'integer':
                    if type(value) is not int or not -MAX_ID - 1 <= value <= MAX_ID:
                        raise ValueError('invalid integer field')
                elif type(value) is not bool:
                    raise ValueError('invalid boolean field')
                values.append(value)
            return values

        def serialize(self, row, fields):
            record = dict(row)
            for field in fields:
                key = field['name']
                if field['type'] == 'boolean' and record[key] is not None:
                    record[key] = bool(record[key])
            return record

        def route(self, method):
            if self.path == '/health' and method == 'GET':
                return self.respond(200, {'status': 'ok', 'project': project})
            match = re.fullmatch(r'/v1/([a-z][a-z0-9_]{0,39})(?:/([1-9][0-9]{0,18}))?(?:[?]after=([0-9]{1,19}))?', self.path)
            if match is None or match[1] not in routes:
                return self.respond(404, {'error': 'route not found'})
            name, identifier, after = match.groups()
            if (identifier is not None and int(identifier) > MAX_ID
                    or after is not None and (int(after) > MAX_ID
                                               or identifier is not None or method != 'GET')):
                return self.respond(400, {'error': 'invalid identifier or cursor'})
            if (identifier is None and method not in {'POST', 'GET'}
                    or identifier is not None and method == 'POST'):
                return self.respond(405, {'error': 'method not allowed'})
            fields = routes[name]
            values = self.read_values(fields) if method in {'POST', 'PUT'} else []
            table = quoted(name)
            columns = [quoted(field['name']) for field in fields]
            with contextlib.closing(sqlite3.connect(db_path)) as db:
                db.row_factory = sqlite3.Row
                with db:
                    if method == 'GET' and identifier is None:
                        rows = db.execute(f'SELECT * FROM {table} WHERE id > ? ORDER BY id LIMIT 101',
                                          (int(after or 0),)).fetchall()
                        return self.respond(200, {
                            'items': [self.serialize(row, fields) for row in rows[:100]],
                            'next_after': rows[99]['id'] if len(rows) > 100 else None,
                        })
                    if method == 'POST':
                        marks = ', '.join('?' for _ in columns)
                        identifier = db.execute(
                            f'INSERT INTO {table} ({", ".join(columns)}) VALUES ({marks})', values
                        ).lastrowid
                    if method == 'PUT':
                        assignments = ', '.join(column + ' = ?' for column in columns)
                        db.execute(f'UPDATE {table} SET {assignments} WHERE id = ?', (*values, int(identifier)))
                    if method == 'DELETE':
                        deleted = db.execute(f'DELETE FROM {table} WHERE id = ?', (int(identifier),)).rowcount
                        status, payload = (200, {'deleted': True}) if deleted else (404, {'error': 'record not found'})
                    else:
                        row = db.execute(f'SELECT * FROM {table} WHERE id = ?', (int(identifier),)).fetchone()
                        status = (201 if method == 'POST' else 200) if row else 404
                        payload = self.serialize(row, fields) if row else {'error': 'record not found'}
            return self.respond(status, payload)

        def handle_method(self, method):
            try:
                self.route(method)
            except (ValueError, UnicodeError, RecursionError):
                self.respond(400, {'error': 'invalid request'})
            except TypeError:
                self.respond(415, {'error': 'JSON content type required'})
            except OverflowError:
                self.respond(413, {'error': 'request too large'})
            except sqlite3.Error:
                self.respond(500, {'error': 'storage operation failed'})

        def do_GET(self):
            self.handle_method('GET')

        def do_POST(self):
            self.handle_method('POST')

        def do_PUT(self):
            self.handle_method('PUT')

        def do_DELETE(self):
            self.handle_method('DELETE')

    return API


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', required=True)
    options = parser.parse_args()
    # Socket and newly created SQLite sidecar files inherit this process umask.
    os.umask(0o077)
    state = state_directory(options.state_dir)
    config = json.loads(read_bound('requirements.json', CONFIG_SHA256))
    schema = read_bound('schema.sql', SCHEMA_SHA256).decode('utf-8')
    db = state / 'data.sqlite3'
    endpoint = state / 'api.sock'
    if len(os.fsencode(endpoint)) >= 104:
        raise ValueError('choose a shorter state directory for the Unix socket')
    initialize_database(db, schema, config['storage_identity'])
    with LocalServer(str(endpoint), handler(config['resources'], db, config['project'])) as server:
        try:
            signal.signal(signal.SIGTERM, lambda *_: raise_exit())
            server.serve_forever(poll_interval=0.05)
        finally:
            endpoint.unlink()


def raise_exit():
    raise SystemExit


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, sqlite3.Error) as error:
        raise SystemExit('Application startup failed: ' + str(error)) from None
'''


def _name(value):
    if not isinstance(value, str) or not _NAME.fullmatch(value) or value.startswith('sqlite_'):
        raise FactoryError('Invalid SQL resource or field name')
    return value


def _request(value):
    _exact(value, {'schema_version', 'project', 'source_revision', 'resources'}, 'generator request')
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise FactoryError('Invalid generator schema version')
    _identifier(value['project'])
    _revision(value['source_revision'])
    resources = {}
    for row in _list(value['resources'], 'resources', 8):
        _exact(row, {'name', 'fields'}, 'resource')
        name = _name(row['name'])
        if name == 'health' or name in resources:
            raise FactoryError('Duplicate or reserved resource')
        fields = {}
        for field in _list(row['fields'], 'fields', 16):
            _exact(field, {'name', 'type', 'required'}, 'field')
            key = _name(field['name'])
            if key in {'id', 'rowid', 'oid', '_rowid_'} or key in fields:
                raise FactoryError('Duplicate or reserved field')
            if (not isinstance(field['type'], str) or field['type'] not in _FIELD_TYPES
                    or type(field['required']) is not bool):
                raise FactoryError('Invalid field type or requirement')
            fields[key] = field.copy()
        resources[name] = {'name': name, 'fields': [fields[key] for key in sorted(fields)]}
    return {**value, 'resources': [resources[key] for key in sorted(resources)]}


def _openapi(config):
    paths = {}
    for row in config['resources']:
        name, fields = row['name'], row['fields']
        base = '/v1/' + name
        properties = {}
        for field in fields:
            kind = {'text': 'string', 'integer': 'integer', 'boolean': 'boolean'}[field['type']]
            properties[field['name']] = {'type': kind if field['required'] else [kind, 'null']}
            if kind == 'integer':
                properties[field['name']]['format'] = 'int64'
        body = {'required': True, 'content': {'application/json': {'schema': {
            'type': 'object', 'additionalProperties': False, 'properties': properties,
            'required': [field['name'] for field in fields if field['required']],
        }}}}
        paths[base] = {
            'get': {'parameters': [{'name': 'after', 'in': 'query', 'required': False,
                                    'schema': {'type': 'integer', 'minimum': 0}}],
                    'responses': {'200': {'description': 'A page of up to 100 records'}}},
            'post': {'requestBody': body, 'responses': {'201': {'description': 'Created record'}}},
        }
        paths[base + '/{id}'] = {
            'parameters': [{'name': 'id', 'in': 'path', 'required': True,
                            'schema': {'type': 'integer', 'minimum': 1}}],
            'get': {'responses': {'200': {'description': 'Record'}, '404': {'description': 'Not found'}}},
            'put': {'requestBody': body, 'responses': {'200': {'description': 'Replaced record'},
                                                     '404': {'description': 'Not found'}}},
            'delete': {'responses': {'200': {'description': 'Deleted'}, '404': {'description': 'Not found'}}},
        }
    paths['/health'] = {'get': {'responses': {'200': {'description': 'Application health'}}}}
    return {'openapi': '3.1.0', 'info': {'title': config['project'], 'version': '1.0.0'}, 'paths': paths}


def _artifacts(config):
    plan = plan_factory({
        'schema_version': 1, 'project': config['project'], 'source_revision': config['source_revision'],
        'targets': ['api', 'backend', 'database'],
        'requirements': [{'id': row['name'], 'summary': 'Serve a private CRUD resource named ' + row['name'],
                          'acceptance': ['create', 'get', 'list', 'replace', 'delete', 'restart-persistence']}
                         for row in config['resources']],
    })
    identity = sha({'project': config['project'], 'resources': config['resources']})
    config = {**config, 'storage_identity': identity}
    config_bytes = canonical(config) + b'\n'
    schema = ['CREATE TABLE "__factory" (identity TEXT PRIMARY KEY NOT NULL);']
    for row in config['resources']:
        columns = ['id INTEGER PRIMARY KEY AUTOINCREMENT']
        for field in row['fields']:
            key = '"' + field['name'] + '"'
            column = key + ' ' + _FIELD_TYPES[field['type']]
            if field['required']:
                column += ' NOT NULL'
            if field['type'] == 'boolean':
                column += f' CHECK ({key} IN (0, 1))'
            columns.append(column)
        schema.append('CREATE TABLE "' + row['name'] + '" (' + ', '.join(columns) + ') STRICT;')
    schema_bytes = ('\n'.join(schema) + '\n').encode()
    script = (_RUNTIME.replace('@CONFIG_SHA256@', hashlib.sha256(config_bytes).hexdigest())
              .replace('@SCHEMA_SHA256@', hashlib.sha256(schema_bytes).hexdigest())
              .replace('@MAX_TEXT@', str(MAX_TEXT)).replace('@MAX_BODY@', str(MAX_BODY)))
    readme = """# Generated private CRUD application

Requires POSIX Unix sockets, Python 3.11+ and SQLite 3.37+.

```sh
python3 app.py --state-dir /tmp/private-project-state
curl --unix-socket /tmp/private-project-state/api.sock http://localhost/health
```

Run under the account that owns the state directory. Choose a short, new or
user-owned mode 0700 state path outside Git. CRUD routes are in openapi.json.
Collection GET returns up to 100 records and a next_after cursor. PUT replaces
all fields. Optional fields accept null. Text is limited to 1024 UTF-8 bytes.
A projection change requires a separately reviewed migration. The transport is
local to this operating-system user and provides no multitenancy or release
authorization.
"""
    return {'app.py': script.encode(), 'requirements.json': config_bytes, 'schema.sql': schema_bytes,
            'openapi.json': canonical(_openapi(config)) + b'\n', 'plan.json': canonical(plan) + b'\n',
            'README.md': readme.encode()}


def _write_files(directory, files):
    for name, data in files.items():
        fd = _open_private(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())


class _UnixHTTP(http.client.HTTPConnection):
    def __init__(self, socket_path):
        super().__init__('localhost', timeout=2)
        self.socket_path = socket_path

    def connect(self):
        with contextlib.ExitStack() as stack:
            connection = stack.enter_context(socket.socket(socket.AF_UNIX, socket.SOCK_STREAM))
            connection.settimeout(self.timeout)
            connection.connect(str(self.socket_path))
            stack.pop_all()
        self.sock = connection


def _call(endpoint, method, path, status, value=None, *, raw=None):
    connection = _UnixHTTP(endpoint)
    try:
        body = raw if raw is not None else canonical(value) if value is not None else None
        headers = {'Content-Type': 'application/json'} if body is not None else {}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        if response.status != status:
            raise FactoryError(f'Generated HTTP verification failed for {method}: {response.status} != {status}')
        result = response.read(MAX_BODY * 100 + 1)
        if len(result) > MAX_BODY * 100:
            raise FactoryError('Generated HTTP response exceeded verification bound')
        return load_json(result)
    finally:
        connection.close()


@contextlib.contextmanager
def _server(directory, project):
    state = directory / 'run'
    endpoint = state / 'api.sock'
    process = subprocess.Popen(
        [sys.executable, '-I', '-B', str(directory / 'app.py'), '--state-dir', str(state)],
        cwd=directory, env={'LC_ALL': 'C.UTF-8'}, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 5
        while True:
            if process.poll() is not None or time.monotonic() >= deadline:
                raise FactoryError('Generated application did not start')
            try:
                health = _call(endpoint, 'GET', '/health', 200)
                break
            except (FileNotFoundError, ConnectionRefusedError):
                time.sleep(0.02)
        if health != {'status': 'ok', 'project': project}:
            raise FactoryError('Generated health endpoint did not match its project')
        yield endpoint
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)


def _same(actual, expected):
    if canonical(actual) != canonical(expected):
        raise FactoryError('Generated application response differs from expected values')


def _fixture(fields, alternate=False):
    values = {'text': 'Updated مرحبًا' if alternate else 'Recorded مرحبًا',
              'integer': -19 if alternate else 17, 'boolean': not alternate}
    return {field['name']: values[field['type']] for field in fields
            if field['required'] or not alternate}


def _verify(config, files):
    with tempfile.TemporaryDirectory(prefix='gaie-api-') as temporary:
        directory = pathlib.Path(temporary)
        _write_files(directory, files)
        records = {}
        with _server(directory, config['project']) as endpoint:
            for row in config['resources']:
                fields = row['fields']
                base = '/v1/' + row['name']
                values = _fixture(fields)
                created = _call(endpoint, 'POST', base, 201, values)
                identifier = created.get('id')
                if type(identifier) is not int or identifier < 1:
                    raise FactoryError('Generated row has no stable integer ID')
                detail = f'{base}/{identifier}'
                _same(created, {'id': identifier, **values})
                _same(_call(endpoint, 'GET', detail, 200), created)
                _same(_call(endpoint, 'GET', base, 200), {'items': [created], 'next_after': None})
                _same(_call(endpoint, 'GET', f'{base}?after={identifier}', 200),
                      {'items': [], 'next_after': None})
                _call(endpoint, 'POST', base, 400, {**values, 'bad_field': True})
                _call(endpoint, 'POST', base, 400, {**values, fields[0]['name']: []})
                _call(endpoint, 'POST', base, 400, raw=b'{"x":1,"x":2}')
                _call(endpoint, 'POST', base, 413, raw=b' ' * (MAX_BODY + 1))
                update = _fixture(fields, alternate=True)
                expected = {'id': identifier, **{field['name']: update.get(field['name']) for field in fields}}
                _same(_call(endpoint, 'PUT', detail, 200, update), expected)
                records[detail] = expected
        # A fresh process reads the same SQLite database and persists deletion.
        with _server(directory, config['project']) as endpoint:
            for detail, record in records.items():
                _same(_call(endpoint, 'GET', detail, 200), record)
                _same(_call(endpoint, 'DELETE', detail, 200), {'deleted': True})
                _call(endpoint, 'GET', detail, 404)
        with _server(directory, config['project']) as endpoint:
            for detail in records:
                _call(endpoint, 'GET', detail, 404)
    return {'status': 'passed', 'transport': 'http-over-unix', 'starts': 3,
            'resources': sorted(row['name'] for row in config['resources']),
            'checks': ['health', 'create', 'read', 'list', 'cursor', 'replace', 'delete',
                       'invalid-fields', 'duplicate-json', 'oversized-body', 'restart-persistence']}


def generate_system(request, *, destination, verify=True):
    """Generate fixed CRUD artifacts at a new private destination and return proof.

    Source revision labels come from the caller. The manifest hashes the generated
    files and this generator. Only fresh, fixed generated code runs in verification.
    Verification uses synthetic values and keeps its state outside the destination.
    """
    config = _request(request)
    if type(verify) is not bool:
        raise FactoryError('Verification flag must be boolean')
    target = pathlib.Path(destination).absolute()
    if '..' in target.parts or not target.name or target.name.startswith('.'):
        raise FactoryError('Invalid system destination')
    if not target.parent.is_dir():
        raise FactoryError('System destination parent must exist and be user-private')
    _safe_directory(target.parent)
    if target.exists() or target.is_symlink():
        raise FactoryError('System destination already exists')
    files = _artifacts(config)
    checks = _verify(config, files) if verify else {'status': 'unverified'}
    result = {
        'schema_version': 1, 'project': config['project'], 'source_revision': config['source_revision'],
        'profile': 'private-sqlite-crud', 'request_sha256': sha(config),
        'generator_sha256': hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
        'files_sha256': {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())},
        'verification': checks, 'deployment_authorized': False,
    }
    result['manifest_sha256'] = sha(result)
    files['manifest.json'] = canonical(result) + b'\n'
    target.mkdir(mode=0o700)
    try:
        _write_files(target, files)
        fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except BaseException:
        for name in files:
            (target / name).unlink(missing_ok=True)
        target.rmdir()
        raise
    return result
