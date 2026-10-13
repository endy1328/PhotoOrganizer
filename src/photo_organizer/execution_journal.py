"""Durable per-stage execution events, independent of media and Qt."""
from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path
from uuid import uuid4

CANCELED_PENDING_MESSAGE = '사용자 요청으로 최종 게시 전에 취소; 임시 파일 정리 완료'


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _record(value):
    if type(value) is not dict or set(value) - {'state', 'attempt_id', 'fingerprint', 'message', 'temp_path'}:
        raise ValueError('실행 단계 기록이 올바르지 않습니다.')
    result = {'state': 'PENDING', 'attempt_id': '', 'fingerprint': {}, 'message': '', 'temp_path': ''}
    result.update(copy.deepcopy(value))
    if type(result['state']) is not str or result['state'] not in {'PENDING', 'IN_PROGRESS', 'DONE', 'FAILED', 'UNCERTAIN', 'NOT_REQUIRED', 'SKIPPED', 'SIZE_EXCLUDED'}:
        raise ValueError('실행 단계 상태가 올바르지 않습니다.')
    for name in ('attempt_id', 'message', 'temp_path'):
        if type(result[name]) is not str or '\x00' in result[name]:
            raise ValueError('실행 단계 문자열이 올바르지 않습니다.')
    if type(result['fingerprint']) is not dict:
        raise ValueError('실행 파일 확인 기록이 올바르지 않습니다.')
    return result


class ExecutionJournal:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.db_path = self.base_dir / 'sessions' / 'execution_journal.sqlite'
        self.journal_path = self.db_path
        self._plans = {}

    def _cache(self, job, manifest, initial):
        self._plans[job.plan_id] = {
            'execution_id': job.execution_id, 'signature': job.plan_signature,
            'manifest': manifest, 'initial': initial,
            'items': {item.item_id: index for index, item in enumerate(job.preview_bundle.preview_items)},
            'records': {row['item_id']: row for row in manifest['items']},
        }

    @staticmethod
    def _transition(previous, record):
        state = record['state']
        previous_state = previous['state']
        if previous_state in {'DONE', 'NOT_REQUIRED', 'SKIPPED', 'SIZE_EXCLUDED', 'UNCERTAIN'}:
            raise ValueError('종료된 단계 기록은 다시 실행하거나 변경할 수 없습니다.')
        if previous_state in {'PENDING', 'FAILED'} and state not in {'IN_PROGRESS', 'FAILED'}:
            raise ValueError('단계 시작 의도 없이 완료를 기록할 수 없습니다.')
        if previous_state == 'IN_PROGRESS':
            if state in {'PENDING', 'NOT_REQUIRED'}:
                if not (state == 'PENDING' and record['message'] == CANCELED_PENDING_MESSAGE
                        and record['fingerprint'] == {} and record['temp_path'] == ''
                        and previous['fingerprint'] == {}
                        and previous['message'] != '최종 파일 게시 시작'):
                    raise ValueError('진행 중인 단계의 실행 의도를 초기화할 수 없습니다.')
            if record['attempt_id'] != previous['attempt_id']:
                raise ValueError('진행 중인 단계의 시도 식별자를 바꿀 수 없습니다.')

    def cancel_pending(self, job, item_id, stage, attempt_id):
        """Caller must first clean its owned staging file before using this path."""
        self.update(job, item_id, stage, {'state': 'PENDING', 'attempt_id': attempt_id,
                    'fingerprint': {}, 'temp_path': '', 'message': CANCELED_PENDING_MESSAGE})

    @staticmethod
    def _rollback(connection):
        try:
            if connection.in_transaction:
                connection.execute('ROLLBACK')
        except sqlite3.Error:
            # Closing the connection below releases the transaction. Preserve
            # the original failure rather than replacing it with cleanup failure.
            pass

    def _connect(self, write=False):
        connection = None
        try:
            if write:
                connection = sqlite3.connect(str(self.db_path), timeout=15, isolation_level=None)
                connection.execute('PRAGMA synchronous=FULL')
            else:
                # SELECT may need SQLite to roll back a hot journal after process
                # death. Allow recovery of this existing app-owned database;
                # mode=rw never creates a missing database or parent directory.
                # Restore itself still issues only read queries, never media changes.
                connection = sqlite3.connect(self.db_path.resolve().as_uri() + '?mode=rw', uri=True, timeout=15, isolation_level=None)
            connection.row_factory = sqlite3.Row
            return connection
        except sqlite3.Error as exc:
            if connection is not None:
                connection.close()
            raise ValueError('실행 저널을 열 수 없습니다. 기존 기록을 확인해 주세요.') from exc

    def _read_plan(self, connection, plan_id):
        try:
            return connection.execute('SELECT * FROM plans WHERE plan_id=?', (plan_id,)).fetchone()
        except sqlite3.Error as exc:
            raise ValueError('실행 저널 구조가 손상되었거나 지원되지 않습니다.') from exc

    def register(self, job):
        from .resume_models import ensure_plan, initial_ledger, plan_manifest, validate_ledger
        if job.legacy_unverified:
            raise ValueError('기존 실행 기록에는 단계별 실행 근거가 없습니다.')
        ensure_plan(job)
        if not job.plan_id or job.preview_bundle is None:
            raise ValueError('등록할 미리보기 계획이 없습니다.')
        ledger = copy.deepcopy(job.ledger or initial_ledger(job))
        candidate = copy.copy(job)
        candidate.ledger = ledger
        validate_ledger(candidate)
        manifest = _json(plan_manifest(job))
        new_execution_id = job.execution_id or str(uuid4())
        existed = self.db_path.exists()
        if not existed:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = self._connect(write=True)
        try:
            connection.execute('BEGIN IMMEDIATE')
            if not existed:
                connection.execute('CREATE TABLE plans (plan_id TEXT PRIMARY KEY, execution_id TEXT UNIQUE NOT NULL, manifest TEXT NOT NULL, initial_ledger TEXT NOT NULL)')
                connection.execute('CREATE TABLE events (plan_id TEXT NOT NULL, seq INTEGER NOT NULL, item_id TEXT NOT NULL, stage TEXT NOT NULL, record TEXT NOT NULL, PRIMARY KEY(plan_id,seq), FOREIGN KEY(plan_id) REFERENCES plans(plan_id))')
                connection.execute('CREATE INDEX events_stage ON events(plan_id,item_id,stage,seq)')
            existing = self._read_plan(connection, job.plan_id)
            if existing is not None:
                count = connection.execute('SELECT COUNT(*) FROM events WHERE plan_id=?', (job.plan_id,)).fetchone()[0]
                if (job.execution_id and job.execution_id == existing['execution_id'] and job.checkpoint == 0 and count == 0
                        and manifest == existing['manifest'] and _json(ledger) == existing['initial_ledger']):
                    connection.execute('COMMIT')
                    job.ledger = ledger
                    job.execution_started = True
                    job.phase = 'EXECUTING'
                    self._cache(job, json.loads(manifest), copy.deepcopy(ledger))
                    return
                raise ValueError('이 미리보기 계획은 이미 실행이 등록되었습니다. 저장된 실행 기록을 불러오세요.')
            if job.execution_started or job.checkpoint:
                raise ValueError('진행 기록이 있는 작업을 새로운 실행으로 등록할 수 없습니다.')
            connection.execute('INSERT INTO plans VALUES (?,?,?,?)', (job.plan_id, new_execution_id, manifest, _json(ledger)))
            connection.execute('COMMIT')
        except sqlite3.Error as exc:
            self._rollback(connection)
            raise ValueError('실행 저널을 저장할 수 없습니다.') from exc
        except Exception:
            self._rollback(connection)
            raise
        finally:
            connection.close()
        job.execution_id = new_execution_id
        job.ledger = ledger
        job.execution_started = True
        job.phase = 'EXECUTING'
        job.checkpoint = 0
        self._cache(job, json.loads(manifest), copy.deepcopy(ledger))

    def update(self, job, item_id: str, stage: str, record: dict):
        from .resume_models import validate_ledger, PLAN_ITEM_FIELDS, processing_settings
        if not self.db_path.exists() or not job.execution_id:
            raise ValueError('등록된 실행 저널이 없습니다.')
        if item_id not in job.ledger or stage not in {'main', 'output', 'source_remove'}:
            raise ValueError('실행 단계 대상이 올바르지 않습니다.')
        normalized = _record(record)
        self._transition(job.ledger[item_id][stage], normalized)
        cache = self._plans.get(job.plan_id)
        if cache is None:
            if not self.restore(job):
                raise ValueError('실행 저널에서 작업 계획을 확인할 수 없습니다.')
            cache = self._plans[job.plan_id]
        if cache['execution_id'] != job.execution_id or cache['signature'] != job.plan_signature:
            raise ValueError('등록한 실행 계획의 식별자가 변경되었습니다.')
        item = job.preview_bundle.preview_items[cache['items'][item_id]]
        current_item = {name: getattr(item, name, '') for name in PLAN_ITEM_FIELDS}
        current_settings = processing_settings(job.settings)
        if (current_item != cache['records'][item_id] or current_settings != cache['manifest']['settings']
                or job.source_fingerprints.get(item.source_path) != cache['manifest']['source_fingerprints'].get(item.source_path)):
            raise ValueError('등록한 실행 계획의 항목이나 설정이 변경되었습니다.')
        candidate = copy.copy(job)
        candidate.preview_bundle = copy.copy(job.preview_bundle)
        candidate.preview_bundle.preview_items = [item]
        candidate.ledger = {item_id: dict(job.ledger[item_id], **{stage: normalized})}
        validate_ledger(candidate)
        connection = self._connect(write=True)
        try:
            connection.execute('BEGIN IMMEDIATE')
            plan = connection.execute('SELECT execution_id FROM plans WHERE plan_id=?', (job.plan_id,)).fetchone()
            if plan is None or plan['execution_id'] != job.execution_id:
                raise ValueError('실행 저널과 작업 계획이 일치하지 않습니다.')
            latest = connection.execute('SELECT COALESCE(MAX(seq),0) FROM events WHERE plan_id=?', (job.plan_id,)).fetchone()[0]
            if latest != job.checkpoint:
                raise ValueError('실행 저널에 더 최신 기록이 있습니다. 작업을 다시 열어 주세요.')
            for sibling in ('main', 'output', 'source_remove'):
                prior = connection.execute('SELECT record FROM events WHERE plan_id=? AND item_id=? AND stage=? ORDER BY seq DESC LIMIT 1', (job.plan_id, item_id, sibling)).fetchone()
                expected = json.loads(prior['record']) if prior is not None else cache['initial'][item_id][sibling]
                if expected != job.ledger[item_id][sibling]:
                    raise ValueError('실행 단계의 현재 기록이 저장된 이력과 다릅니다.')
            sequence = latest + 1
            connection.execute('INSERT INTO events VALUES (?,?,?,?,?)', (job.plan_id, sequence, item_id, stage, _json(normalized)))
            connection.execute('COMMIT')
        except sqlite3.Error as exc:
            self._rollback(connection)
            raise ValueError('실행 단계 기록을 저장할 수 없습니다.') from exc
        except Exception:
            self._rollback(connection)
            raise
        finally:
            connection.close()
        job.ledger[item_id][stage] = normalized
        job.checkpoint = sequence

    def restore(self, job) -> bool:
        """Adopt newer events only after proving the supplied snapshot is a prefix."""
        from .resume_models import plan_manifest, validate_ledger, bundle_from_ledger
        if not self.db_path.exists():
            return False
        if job.legacy_unverified or not job.plan_id:
            return False
        connection = self._connect()
        try:
            connection.execute('BEGIN')
            plan = self._read_plan(connection, job.plan_id)
            if plan is None:
                connection.execute('COMMIT')
                return False
            if plan['manifest'] != _json(plan_manifest(job)) or (job.execution_id and plan['execution_id'] != job.execution_id):
                raise ValueError('저장된 작업과 실행 저널의 계획이 일치하지 않습니다.')
            ledger = json.loads(plan['initial_ledger'])
            initial = copy.deepcopy(ledger)
            validation_job = copy.copy(job)
            validation_job.ledger = ledger
            validate_ledger(validation_job)
            item_index = {item.item_id: item for item in job.preview_bundle.preview_items if item.included}
            latest = 0
            prefix = initial if job.checkpoint == 0 else None
            for row in connection.execute('SELECT seq,item_id,stage,record FROM events WHERE plan_id=? ORDER BY seq', (job.plan_id,)):
                if row['seq'] != latest + 1 or row['item_id'] not in ledger or row['stage'] not in {'main', 'output', 'source_remove'}:
                    raise ValueError('실행 저널 이벤트 이력이 누락되었거나 손상되었습니다.')
                record = json.loads(row['record'])
                if type(record) is not dict or set(record) != {'state', 'attempt_id', 'fingerprint', 'message', 'temp_path'}:
                    raise ValueError('실행 저널 단계 필드가 손상되었습니다.')
                normalized = _record(record)
                self._transition(ledger[row['item_id']][row['stage']], normalized)
                ledger[row['item_id']][row['stage']] = normalized
                validation_job.preview_bundle = copy.copy(job.preview_bundle)
                validation_job.preview_bundle.preview_items = [item_index[row['item_id']]]
                validation_job.ledger = {row['item_id']: ledger[row['item_id']]}
                validate_ledger(validation_job)
                latest = row['seq']
                if latest == job.checkpoint:
                    prefix = copy.deepcopy(ledger)
            old_ready = not job.execution_started and not job.execution_id and job.checkpoint == 0 and not job.ledger
            if prefix is None or job.checkpoint > latest or (not old_ready and _json(prefix) != _json(job.ledger)):
                raise ValueError('저장된 작업의 단계 기록이 실행 저널 이력과 충돌합니다.')
            candidate = copy.copy(job)
            candidate.ledger = ledger
            candidate.execution_id = plan['execution_id']
            candidate.execution_started = True
            candidate.checkpoint = latest
            validate_ledger(candidate)
            bundle = bundle_from_ledger(candidate)
            candidate.execution_bundle = bundle
            included = {p.source_path for p in job.preview_bundle.preview_items if p.included}
            present = {r.source_path for r in bundle.execution_results}
            candidate.phase = 'EXECUTION_FINISHED' if included == present else 'EXECUTION_PARTIAL'
            connection.execute('COMMIT')
        except (sqlite3.Error, json.JSONDecodeError, TypeError, KeyError) as exc:
            raise ValueError('실행 저널을 복원할 수 없습니다. 기존 파일을 보존합니다.') from exc
        finally:
            connection.close()
        for name in ('ledger', 'execution_id', 'execution_started', 'checkpoint', 'execution_bundle', 'phase', 'result_fingerprints'):
            setattr(job, name, getattr(candidate, name))
        self._cache(job, json.loads(plan['manifest']), initial)
        return True
