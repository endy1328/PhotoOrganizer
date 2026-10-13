from __future__ import annotations

import ctypes
import shutil
import re
import tempfile
import os
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

try:
    from send2trash import send2trash  # type: ignore
except Exception:
    send2trash = None

try:
    from PIL import Image  # type: ignore
except Exception:
    Image = None

try:
    from PIL import PngImagePlugin  # type: ignore
except Exception:
    PngImagePlugin = None

from .fallback import canonical_model_key, infer_video_model_from_media, find_video_model_candidate, sanitize_model_name, explain_video_model_failure, find_video_model_candidate_unbounded_photos, explain_unbounded_photo_failure
from .logging_utils import AppLogger
from .metadata import MetadataExtractor
from .models import (
    DeleteReviewItem,
    ErrorItem,
    ExecutionBundle,
    ExecutionResult,
    LogEvent,
    MediaItem,
    OrganizeRequest,
    PreviewBundle,
    PreviewItem,
    SUPPORTED_EXTENSIONS,
)
from .video_output import create_mobile_video_output
from .file_times import set_capture_file_times
from .model_mapping import validate_model_mappings, resolve_output_model_name, normalize_model_mapping_scope, model_mapping_signature


class MobileOutputSizeExcluded(Exception):
    """Converted output was deliberately omitted; regular organization succeeded."""


class OrganizerEngine:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path.cwd()
        self.extractor = MetadataExtractor()
        self.logger = AppLogger(self.base_dir)

    def preview(
        self, request: OrganizeRequest, progress_callback=None, control=None,
    ) -> PreviewBundle:
        try:
            return self._preview(request, progress_callback, control)
        finally:
            if control is not None:
                from .isolated_work import close_workers
                close_workers(control)

    def _preview(
        self,
        request: OrganizeRequest,
        progress_callback: Callable[[str, int, int], None] | None = None,
        control=None,
    ) -> PreviewBundle:
        self._preview_checkpoint(control)
        mappings = validate_model_mappings(request.model_name_mappings)
        self._report_progress(progress_callback, "파일 스캔 중", 0, 0)
        items = (self._scan_media_files(request.source_path, request.target_path) if control is None else
                 self._scan_media_files(request.source_path, request.target_path, control=control))
        total_items = len(items)
        self._report_progress(progress_callback, "메타데이터 읽는 중", 0, total_items)
        media_items: list[MediaItem] = []
        for index, path in enumerate(items, start=1):
            from .operation_control import OperationInterrupted
            while True:
                self._preview_checkpoint(control)
                try:
                    with (control.file_activity(str(path), path, 'metadata') if control is not None else nullcontext()):
                        if control is not None and self._native_extractor():
                            from .isolated_work import isolated_call
                            item = isolated_call('metadata', (path,))
                        else:
                            item = self.extractor.extract(path)
                        if control is not None:
                            control.raise_if_interrupted()
                        media_items.append(item)
                    break
                except OperationInterrupted:
                    self._preview_checkpoint(control)
            self._report_progress(progress_callback, "메타데이터 읽는 중", index, total_items)
        self._preview_checkpoint(control)
        self._report_progress(progress_callback, "영상 모델명 정리 중", 0, total_items)
        self._infer_video_models(media_items, request.video_model_window_minutes, **({'control': control} if control else {}))
        self._apply_device_name_override(media_items, request.device_name_override)
        self._normalize_model_names(media_items)
        self._report_progress(progress_callback, "미리보기 생성 중", 0, total_items)
        preview_items, error_items, log_events = self._build_preview(media_items, request.target_path, request,
                                                                    **({'control': control} if control else {}))
        self._preview_checkpoint(control)
        self._report_progress(progress_callback, "미리보기 완료", total_items, total_items)
        return PreviewBundle(preview_items=preview_items, error_items=error_items, log_events=log_events,
                             media_items=media_items, model_name_mappings=mappings,
                             model_mapping_scope=normalize_model_mapping_scope(request.model_mapping_scope))

    def execute(
        self,
        request: OrganizeRequest,
        progress_callback: Callable[[str, int, int], None] | None = None,
        preview_bundle: PreviewBundle | None = None,
        job_state=None,
        control=None,
    ) -> ExecutionBundle:
        if job_state is not None:
            from .resume_engine import execute_job
            options = {"control": control} if control is not None else {}
            return execute_job(self, job_state, mode="initial", progress_callback=progress_callback, **options)
        self._validate_mobile_output_limit(request)
        if preview_bundle is None:
            options = {"control": control} if control is not None else {}
            preview_bundle = self.preview(request, progress_callback=progress_callback, **options)
        if model_mapping_signature(request.model_name_mappings, request.model_mapping_scope) != model_mapping_signature(
                preview_bundle.model_name_mappings, preview_bundle.model_mapping_scope):
            raise ValueError("모델명 매핑 설정이 변경되었습니다. 미리보기를 다시 만들어주세요.")
        results: list[ExecutionResult] = []
        delete_review_items: list[DeleteReviewItem] = []
        log_events = list(preview_bundle.log_events)
        included_items = [item for item in preview_bundle.preview_items if item.included]
        total_items = len(included_items)
        self._report_progress(progress_callback, "파일 정리 실행 중", 0, total_items)
        for index, preview_item in enumerate(included_items, start=1):
            if control is not None and not control.checkpoint():
                break
            source = Path(preview_item.source_path)
            target = Path(preview_item.target_path)
            converter_called = False
            with (control.file_activity(preview_item.item_id, source, 'copy') if control is not None else nullcontext()):
                try:
                    if preview_item.write_mode == "CONFLICT":
                        raise FileExistsError("출력 파일명이 기존 파일 또는 다른 처리 항목과 충돌합니다.")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if preview_item.filename_edited:
                        self._validate_manual_filename(preview_item.new_filename, source.suffix)
                        if target != Path(preview_item.target_directory) / preview_item.new_filename:
                            raise ValueError("사용자 지정 파일명과 대상 경로가 일치하지 않습니다.")
                        if preview_item.mobile_output_path and Path(preview_item.mobile_output_path).exists():
                            raise FileExistsError("모바일 출력 파일이 이미 존재합니다.")
                        self._copy_exclusive(source, target)
                        action = request.operation_mode
                        mobile_output_source = target if action == "move" else source
                    elif request.operation_mode == "move":
                        if preview_item.write_mode == "OVERWRITE" and target.exists():
                            target.unlink()
                        shutil.move(str(source), str(target))
                        action = "move"
                        mobile_output_source = target
                    else:
                        shutil.copy2(str(source), str(target))
                        action = "copy"
                        mobile_output_source = source
                    mobile_output_status = ""
                    mobile_output_message = ""
                    if preview_item.mobile_output_enabled and preview_item.mobile_output_path:
                        create_output = self._create_mobile_output_exclusive if preview_item.filename_edited else self._create_mobile_output
                        try:
                            if preview_item.media_type == "video":
                                from .video_output import clear_video_encoder_report
                                clear_video_encoder_report()
                            converter_called = True
                            if control is not None:
                                control.update_file_activity(preview_item.item_id, 'output')
                            mobile_output_status = create_output(
                                source_path=mobile_output_source,
                                target_path=Path(preview_item.mobile_output_path),
                                media_type=preview_item.media_type,
                                request=request,
                            )
                        except MobileOutputSizeExcluded as exc:
                            mobile_output_status = "SIZE_EXCLUDED"
                            mobile_output_message = str(exc)
                            log_events.append(LogEvent("INFO", mobile_output_message, str(source),
                                                       preview_item.mobile_output_path))
                        if preview_item.media_type == "video":
                            from .video_output import get_last_video_encoder_report
                            report = get_last_video_encoder_report()
                            if report:
                                mobile_output_message = "; ".join(part for part in (mobile_output_message, report) if part)
                        if mobile_output_status == "SUCCESS":
                            set_capture_file_times(
                                Path(preview_item.mobile_output_path),
                                datetime.fromisoformat(preview_item.captured_at),
                            )
                    if preview_item.filename_edited and request.operation_mode == "move":
                        if control is not None:
                            control.update_file_activity(preview_item.item_id, 'source_remove')
                        source.unlink()  # 사용자 지정 출력이 모두 성공한 뒤에만 원본 경로를 제거한다.
                    if request.operation_mode == "copy":
                        delete_review_items.append(
                            DeleteReviewItem(
                                item_id=preview_item.item_id,
                                delete_path=str(source),
                                reason="복사 완료 후 원본 정리 후보",
                            )
                        )
                    results.append(
                        ExecutionResult(
                            source_path=str(source),
                            target_path=str(target),
                            status="SUCCESS",
                            action=action,
                            write_mode=preview_item.write_mode,
                            message=preview_item.write_mode,
                            mobile_output_path=preview_item.mobile_output_path,
                            mobile_output_status=mobile_output_status,
                            mobile_output_message=mobile_output_message,
                        )
                    )
                    if control is not None:
                        control.report_file_result(preview_item.item_id, source,
                                                   'ERROR' if mobile_output_status == 'ERROR' else 'SUCCESS',
                                                   mobile_output_message if mobile_output_status == 'ERROR' else '')
                    log_events.append(
                        LogEvent(
                            level="INFO",
                            message=f"{action.upper()} {preview_item.write_mode} 성공",
                            source_path=str(source),
                            target_path=str(target),
                        )
                    )
                except Exception as exc:
                    encoder_report = ""
                    if converter_called and preview_item.media_type == "video":
                        from .video_output import get_last_video_encoder_report
                        encoder_report = get_last_video_encoder_report()
                    results.append(
                        ExecutionResult(
                            source_path=str(source),
                            target_path=str(target),
                            status="ERROR",
                            action=request.operation_mode,
                            write_mode=preview_item.write_mode,
                            message=str(exc),
                            mobile_output_path=preview_item.mobile_output_path,
                            mobile_output_status="ERROR" if preview_item.mobile_output_enabled and preview_item.mobile_output_path else "",
                            mobile_output_message=encoder_report,
                        )
                    )
                    preview_bundle.error_items.append(ErrorItem(source_path=str(source), message=str(exc)))
                    if control is not None:
                        control.report_file_result(preview_item.item_id, source, 'ERROR', str(exc))
                    log_events.append(LogEvent(level="ERROR", message=f"실행 실패: {exc}", source_path=str(source), target_path=str(target)))
                    if (preview_item.write_mode != "CONFLICT" and preview_item.mobile_output_enabled
                            and preview_item.mobile_output_path):
                        break
            self._report_progress(progress_callback, "파일 정리 실행 중", index, total_items)
        self.logger.write_session_log(log_events)
        if control is not None and control.stopped:
            self._report_progress(progress_callback, "실행 중단", len(results), total_items)
        else:
            self._report_progress(progress_callback, "실행 완료", total_items, total_items)
        return ExecutionBundle(
            preview_items=preview_bundle.preview_items,
            execution_results=results,
            error_items=preview_bundle.error_items,
            delete_review_items=delete_review_items,
            log_events=log_events,
        )

    def resume(self, job, mode: str = "continue", progress_callback=None, control=None) -> ExecutionBundle:
        from .resume_engine import execute_job
        options = {"control": control} if control is not None else {}
        return execute_job(self, job, mode=mode, progress_callback=progress_callback, **options)

    @staticmethod
    def _preview_checkpoint(control) -> None:
        if control is not None and not control.checkpoint():
            from .operation_control import OperationStopped
            raise OperationStopped("미리보기를 중단했습니다. 이전 작업 결과를 유지합니다.")

    def _native_extractor(self):
        return (type(self.extractor) is MetadataExtractor and
                getattr(self.extractor.extract, '__func__', None) is MetadataExtractor.extract)

    def set_selected_models(self, bundle: PreviewBundle, selected_models: set[str]) -> None:
        """Re-plan selected rows without rescanning or changing inferred metadata."""
        file_conflict = "날짜 기준 고정 SEQ가 이미 사용 중인 파일과 충돌합니다."
        selection_conflict = "모델 선택 후 출력 경로가 다른 항목 또는 기존 파일과 충돌합니다."
        media_by_path = {str(item.source_path): item for item in bundle.media_items}
        sequence_counters: dict[Path, int] = {}
        candidates = []
        for original in bundle.preview_items:
            item = replace(original, included=original.file_selected and original.model_name in selected_models,
                           warnings=[w for w in original.warnings if w not in {file_conflict, selection_conflict}])
            if item.included:
                directory = Path(item.target_directory)
                seq = self._next_sequence_for_directory(directory.parent, sequence_counters)
                self._remember_next_sequence(directory.parent, seq + 1, sequence_counters)
                if item.filename_edited:
                    item.write_mode = "NEW"
                else:
                    source_item = media_by_path.get(item.source_path) or MediaItem(
                        source_path=Path(item.source_path), media_type=item.media_type,
                        extension=Path(item.source_path).suffix,
                        captured_at=datetime.fromisoformat(item.captured_at),
                        model_name=item.model_name,
                    )
                    item.new_filename, item.write_mode = self._build_target_filename(
                        source_item, directory, seq, allow_overwrite=False,
                        output_model_name=item.output_model_name or item.model_name,
                    )
                    if item.write_mode == "CONFLICT":
                        item.warnings.append(file_conflict)
                item.target_path = str(directory / item.new_filename)
                item.mobile_output_path = (str(self._build_mobile_output_path(directory, item.new_filename))
                                           if item.mobile_output_enabled else "")
            candidates.append(item)

        occupied: dict[str, list[PreviewItem]] = {}
        for item in candidates:
            if not item.included:
                continue
            for path in [item.target_path] + ([item.mobile_output_path] if item.mobile_output_path else []):
                occupied.setdefault(str(Path(path)).casefold(), []).append(item)
                if Path(path).exists() or Path(path).is_symlink():
                    item.write_mode = "CONFLICT"
                    if selection_conflict not in item.warnings:
                        item.warnings.append(selection_conflict)
        for items in occupied.values():
            if len(items) > 1:
                for item in items:
                    item.write_mode = "CONFLICT"
                    if selection_conflict not in item.warnings:
                        item.warnings.append(selection_conflict)
        bundle.preview_items = candidates
        bundle.selection_applied = True
        bundle.selected_models = sorted(selected_models)
        bundle.log_events.append(LogEvent("INFO", f"처리할 모델 선택: {', '.join(sorted(selected_models)) or '없음'}"))

    @staticmethod
    def _selected_models(bundle: PreviewBundle) -> set[str]:
        if bundle.selected_models is not None:
            return set(bundle.selected_models)
        return {item.model_name for item in bundle.preview_items if item.included}

    def set_selected_files(self, bundle: PreviewBundle, item_ids: Iterable[str], selected: bool) -> None:
        """Change individual choices without changing independent model choices."""
        if type(selected) is not bool:
            raise ValueError('파일 선택 여부는 참/거짓이어야 합니다.')
        ids = set(item_ids)
        if ids - {item.item_id for item in bundle.preview_items}:
            raise ValueError('미리보기 항목을 찾을 수 없습니다.')
        models = self._selected_models(bundle)
        candidate = replace(bundle, preview_items=[replace(item, file_selected=selected if item.item_id in ids else item.file_selected)
                                                   for item in bundle.preview_items], log_events=list(bundle.log_events))
        self.set_selected_models(candidate, models)
        candidate.log_events.append(LogEvent('INFO', f'개별 파일 {"포함" if selected else "제외"}: {len(ids)}건'))
        bundle.preview_items = candidate.preview_items
        bundle.selected_models = candidate.selected_models
        bundle.selection_applied = True
        bundle.log_events = candidate.log_events

    def refresh_preview_after_metadata(self, bundle: PreviewBundle, request: OrganizeRequest,
                                       source_path: str | Path) -> PreviewBundle:
        """Read the edited source directory afresh; commit only a complete re-plan.

        Caller must prohibit editing a job whose execution has started and refresh
        its source fingerprints after this method succeeds.
        """
        source = Path(source_path)
        originals = {item.source_path: item for item in bundle.preview_items}
        if str(source) not in originals:
            raise ValueError('미리보기 항목을 찾을 수 없습니다.')
        old_models = {item.model_name for item in bundle.preview_items}
        selected = self._selected_models(bundle)
        try:
            media = []
            available = {item.source_path for item in bundle.media_items}
            for original in bundle.media_items:
                item = (self.extractor.extract(original.source_path)
                        if original.source_path.parent == source.parent else original)
                media.append(replace(item, warnings=list(item.warnings), metadata=dict(item.metadata)))
            # Older saved snapshots may omit media records. Re-read their known
            # rows/errors rather than inventing metadata from formatted filenames.
            for path in dict.fromkeys([Path(item.source_path) for item in bundle.preview_items] +
                                      [Path(item.source_path) for item in bundle.error_items]):
                if path not in available:
                    item = self.extractor.extract(path)
                    media.append(replace(item, warnings=list(item.warnings), metadata=dict(item.metadata)))
            if not any(item.source_path == source and item.ready for item in media):
                raise ValueError('수정한 원본의 메타정보를 다시 읽지 못했습니다.')
            self._infer_video_models(media, request.video_model_window_minutes)
            self._apply_device_name_override(media, request.device_name_override)
            self._normalize_model_names(media)
            rows, errors, events = self._build_preview(media, request.target_path, request)
            candidate = PreviewBundle(preview_items=rows, error_items=errors,
                                      log_events=list(bundle.log_events) + events, media_items=media,
                                      model_name_mappings=validate_model_mappings(request.model_name_mappings),
                                      model_mapping_scope=normalize_model_mapping_scope(request.model_mapping_scope))
            for item in rows:
                previous = originals.get(item.source_path)
                if previous is not None:
                    item.file_selected = previous.file_selected
            new_models = {item.model_name for item in rows} - old_models
            candidate.selected_models = sorted(selected | new_models)
            names = {item.source_path: item.new_filename for item in bundle.preview_items if item.filename_edited}
            self.restore_manual_filenames(candidate, names)
            self.set_selected_models(candidate, set(candidate.selected_models))
        except Exception as exc:
            raise ValueError(f'원본 수정 후 미리보기를 다시 계획하지 못했습니다. 새 미리보기를 실행해주세요: {exc}') from exc
        bundle.preview_items, bundle.error_items = candidate.preview_items, candidate.error_items
        bundle.log_events, bundle.media_items = candidate.log_events, candidate.media_items
        bundle.model_name_mappings, bundle.model_mapping_scope = candidate.model_name_mappings, candidate.model_mapping_scope
        bundle.selected_models, bundle.selection_applied = candidate.selected_models, True
        return bundle

    def restore_manual_filenames(self, bundle: PreviewBundle, names: dict[str, str]) -> int:
        """Restore edits into a new mapped plan; expose all resulting collisions."""
        candidate = replace(bundle, preview_items=[replace(
            item, warnings=list(item.warnings), metadata_entries=list(item.metadata_entries),
        ) for item in bundle.preview_items], log_events=list(bundle.log_events))
        count = 0
        for item in candidate.preview_items:
            if item.source_path not in names:
                continue
            filename = names[item.source_path]
            self._validate_manual_filename(filename, Path(item.source_path).suffix)
            directory = Path(item.target_directory)
            item.new_filename = filename
            item.target_path = str(directory / filename)
            item.mobile_output_path = str(self._build_mobile_output_path(directory, filename)) if item.mobile_output_enabled else ""
            item.filename_edited = True
            item.metadata_entries = [(key, value) for key, value in item.metadata_entries if key != "사용자 지정 파일명"]
            item.metadata_entries.append(("사용자 지정 파일명", filename))
            candidate.log_events.append(LogEvent("INFO", "매핑 변경 후 수동 파일명 유지", item.source_path, item.target_path))
            count += 1
        if count:
            self.set_selected_models(candidate, self._selected_models(candidate))
            bundle.preview_items = candidate.preview_items
            bundle.log_events = candidate.log_events
            bundle.selection_applied = candidate.selection_applied
            bundle.selected_models = candidate.selected_models
        return count

    def edit_preview_filename(self, bundle: PreviewBundle, item_id: str, filename: str) -> PreviewItem:
        item = next((item for item in bundle.preview_items if item.item_id == item_id), None)
        if item is None:
            raise ValueError("미리보기 항목을 찾을 수 없습니다.")
        if not item.included:
            raise ValueError("제외한 파일의 파일명은 수정할 수 없습니다. 먼저 모델과 파일을 처리 대상으로 선택해주세요.")
        self._validate_manual_filename(filename, Path(item.source_path).suffix)
        target = Path(item.target_directory) / filename
        mobile = self._build_mobile_output_path(Path(item.target_directory), filename) if item.mobile_output_enabled else None
        destinations = [target] + ([mobile] if mobile is not None else [])
        for path in destinations:
            if path.exists() or path.is_symlink():
                raise ValueError(f"이미 존재하는 파일명입니다: {path.name}")
            key = str(path).casefold()
            for other in bundle.preview_items:
                if other.item_id == item_id or not other.included:
                    continue
                if key in {str(Path(other.target_path)).casefold(), str(Path(other.mobile_output_path)).casefold() if other.mobile_output_path else ""}:
                    raise ValueError("다른 미리보기 항목의 출력 파일명과 충돌합니다.")
        item.new_filename = filename
        item.target_path = str(target)
        item.mobile_output_path = str(mobile) if mobile is not None else ""
        item.filename_edited = True
        item.write_mode = "NEW"
        item.warnings = [warning for warning in item.warnings if warning != "날짜 기준 고정 SEQ가 이미 사용 중인 파일과 충돌합니다."]
        item.metadata_entries = [(key, value) for key, value in item.metadata_entries if key != "사용자 지정 파일명"]
        item.metadata_entries.append(("사용자 지정 파일명", filename))
        bundle.log_events.append(LogEvent("INFO", "사용자 파일명 수정", item.source_path, item.target_path))
        if bundle.selection_applied:
            self.set_selected_models(bundle, self._selected_models(bundle))
            return next(row for row in bundle.preview_items if row.item_id == item_id)
        return item

    def _validate_manual_filename(self, filename: str, extension: str) -> None:
        if not filename or filename in {".", ".."} or filename[-1:] in {" ", "."}:
            raise ValueError("빈 이름이나 끝의 공백/마침표는 사용할 수 없습니다.")
        if re.search(r'[<>:"/\\|?*\x00-\x1f]', filename):
            raise ValueError("파일명에 경로나 사용할 수 없는 문자가 있습니다.")
        if len(filename.encode("utf-16-le")) // 2 > 255:
            raise ValueError("파일명이 너무 깁니다(최대 255자).")
        reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
        reserved.update({f"{prefix}{digit}" for prefix in ("COM", "LPT") for digit in "¹²³"})
        if filename.split(".", 1)[0].rstrip(" .").upper() in reserved:
            raise ValueError("Windows 예약 파일명은 사용할 수 없습니다.")
        if Path(filename).suffix.casefold() != extension.casefold():
            raise ValueError("원본 확장자를 유지해주세요. 파일명 수정은 포맷 변환이 아닙니다.")

    def _copy_exclusive(self, source: Path, target: Path) -> None:
        # xb는 미리보기 이후 파일이 생겨도 덮어쓰지 않는다. 생성한 부분 파일만 정리한다.
        created = False
        try:
            with source.open("rb") as reader, target.open("xb") as writer:
                created = True
                shutil.copyfileobj(reader, writer)
            shutil.copystat(source, target)
        except Exception:
            if created:
                target.unlink(missing_ok=True)
            raise

    def _create_mobile_output_exclusive(self, source_path: Path, target_path: Path, media_type: str, request: OrganizeRequest) -> str:
        self._validate_mobile_output_limit(request)
        if request.mobile_output_limit_enabled:
            return self._create_size_limited_mobile_output(source_path, target_path, media_type, request, exclusive=True)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists() or target_path.is_symlink():
            raise FileExistsError("모바일 출력 파일이 이미 존재합니다.")
        with tempfile.TemporaryDirectory(dir=target_path.parent, prefix=".photoorganizer_") as temporary:
            staged = Path(temporary) / target_path.name
            status = self._create_mobile_output(source_path, staged, media_type, request)
            if staged.exists():
                self._copy_exclusive(staged, target_path)
            elif status == "SUCCESS":
                raise OSError("모바일 출력 성공 응답에 파일이 없습니다.")
            return status

    def delete_selected(self, items: Iterable[DeleteReviewItem]) -> list[ExecutionResult]:
        results: list[ExecutionResult] = []
        for item in items:
            if not item.selected:
                continue
            path = Path(item.delete_path)
            try:
                self._move_to_recycle_bin(path)
                results.append(
                    ExecutionResult(
                        source_path=str(path),
                        target_path="",
                        status="SUCCESS",
                        action="delete_review",
                        write_mode="DELETE",
                        message="휴지통 이동 완료",
                    )
                )
            except Exception as exc:
                results.append(
                    ExecutionResult(
                        source_path=str(path),
                        target_path="",
                        status="ERROR",
                        action="delete_review",
                        write_mode="DELETE",
                        message=str(exc),
                    )
                )
        if results:
            self.logger.write_session_log(
                [LogEvent(level="INFO" if r.status == "SUCCESS" else "ERROR", message=f"삭제 리뷰 {r.status}", source_path=r.source_path) for r in results]
            )
        return results

    def describe_media_path(self, path: Path) -> list[tuple[str, str]]:
        if not path.exists() or not path.is_file():
            return []
        try:
            item = self.extractor.extract(path)
        except Exception:
            return []
        return self._build_metadata_entries(item)

    def _scan_media_files(self, source_path: Path, target_path: Path | None = None, control=None) -> list[Path]:
        from .metadata_writer import is_metadata_storage
        source_resolved = source_path.resolve()
        target_resolved = target_path.resolve() if target_path else None
        paths: list[Path] = []
        if is_metadata_storage(source_path):
            return paths
        for directory, names, filenames in os.walk(source_path):
            self._preview_checkpoint(control)
            names[:] = [name for name in names if not is_metadata_storage(Path(directory) / name)]
            for filename in filenames:
                path = Path(directory) / filename
                self._preview_checkpoint(control)
                if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                    continue
                try:
                    resolved = path.resolve()
                    if target_resolved and (resolved == target_resolved or target_resolved in resolved.parents):
                        continue
                    if resolved == source_resolved:
                        continue
                except Exception:
                    pass
                paths.append(path)
        return sorted(paths)

    def _infer_video_models(self, media_items: list[MediaItem], window_minutes: int = 5, control=None) -> None:
        photos_by_dir: dict[Path, list[MediaItem]] = {}
        for item in media_items:
            if item.captured_at and canonical_model_key(item.model_name) and "추론" not in item.model_source:
                photos_by_dir.setdefault(item.source_path.parent, []).append(item)
        for item in media_items:
            self._preview_checkpoint(control)
            if item.media_type != "video" or canonical_model_key(item.model_name):
                continue
            candidates = photos_by_dir.get(item.source_path.parent, [])
            model, source = infer_video_model_from_media(item, candidates, window_minutes)
            candidate = find_video_model_candidate(item, candidates, window_minutes) if model else None
            mode = "time_window"
            if not model:
                candidate = find_video_model_candidate_unbounded_photos(item, candidates)
                if candidate is not None:
                    model = candidate.model_name
                    source = "영상 모델명 앞뒤 사진 추론(시간 제한 없음)"
                    mode = "unbounded_photos"
            if model:
                item.model_name = model
                item.model_source = source
                if candidate is not None:
                    item.metadata["model_inference"] = {"status": "found", "mode": mode, "candidate": str(candidate.source_path), "delta_seconds": abs((candidate.captured_at - item.captured_at).total_seconds()), "window_minutes": window_minutes}
            else:
                item.model_name = "UNKNOWN"
                item.model_source = "UNKNOWN"
                reason = explain_video_model_failure(item, candidates, window_minutes)
                unlimited_reason = explain_unbounded_photo_failure(item, candidates)
                item.metadata["model_inference"] = {"status": "not_found", "detail": f"{reason}; 시간 제한 없는 사진 보완: {unlimited_reason}", "window_minutes": window_minutes}

    def _apply_device_name_override(self, media_items: list[MediaItem], device_name_override: str) -> None:
        override_name = sanitize_model_name(device_name_override)
        if not device_name_override.strip() or override_name == "UNKNOWN":
            return
        for item in media_items:
            item.model_name = override_name
            item.model_source = "사용자 입력"

    def _normalize_model_names(self, media_items: list[MediaItem]) -> None:
        grouped_items: dict[str, list[MediaItem]] = {}
        for item in media_items:
            key = canonical_model_key(item.model_name)
            if not key:
                continue
            grouped_items.setdefault(key, []).append(item)
        for items in grouped_items.values():
            representative = self._choose_representative_model_name(items)
            for item in items:
                item.model_name = representative

    def _choose_representative_model_name(self, items: list[MediaItem]) -> str:
        def score(item: MediaItem) -> tuple[int, int, int, str]:
            source_priority = {
                "사용자 입력": 0,
                "사진 메타": 1,
                "영상 메타": 2,
                "영상 모델명 사진 추론": 3,
                "영상 모델명 영상 추론": 3,
                "영상 모델명 앞뒤 사진 추론(시간 제한 없음)": 3,
                "파일명 fallback": 4,
                "UNKNOWN": 5,
            }
            model_name = sanitize_model_name(item.model_name)
            return (
                source_priority.get(item.model_source, 9),
                0 if "_" in model_name else 1,
                -len(model_name),
                model_name.lower(),
            )

        best_item = min(items, key=score)
        return sanitize_model_name(best_item.model_name)

    def _build_preview(
        self,
        media_items: list[MediaItem],
        target_root: Path,
        request: OrganizeRequest,
        control=None,
    ) -> tuple[list[PreviewItem], list[ErrorItem], list[LogEvent]]:
        mappings = validate_model_mappings(request.model_name_mappings)
        scope = normalize_model_mapping_scope(request.model_mapping_scope)
        preview_items: list[PreviewItem] = []
        error_items: list[ErrorItem] = []
        log_events: list[LogEvent] = []
        sequence_counters: dict[Path, int] = {}
        ordered_items = sorted(
            media_items,
            key=lambda item: (
                item.captured_at is None,
                item.captured_at or datetime.min,
                str(item.source_path).lower(),
            ),
        )
        for item in ordered_items:
            self._preview_checkpoint(control)
            if not item.captured_at:
                message = "촬영 일시를 메타데이터와 파일명에서 모두 찾지 못했습니다."
                error_items.append(ErrorItem(source_path=str(item.source_path), message=message, media_type=item.media_type))
                log_events.append(LogEvent(level="WARNING", message=message, source_path=str(item.source_path)))
                continue
            model_name = sanitize_model_name(item.model_name)
            output_model_name = resolve_output_model_name(model_name, mappings)
            folder_model_name = output_model_name if scope == "filename_and_folders" else model_name
            target_dir = self._build_target_directory(target_root, item.captured_at, model_name,
                                                      output_model_name=folder_model_name)
            # 같은 날짜의 모델/UNKNOWN 폴더들이 하나의 SEQ 흐름을 공유한다.
            sequence_directory = target_dir.parent
            seq = self._next_sequence_for_directory(sequence_directory, sequence_counters)
            self._remember_next_sequence(sequence_directory, seq + 1, sequence_counters)
            target_filename, write_mode = self._build_target_filename(item, target_dir, seq,
                                                                      output_model_name=output_model_name,
                                                                      **({'control': control} if control else {}))
            target_path = target_dir / target_filename
            mobile_output_path = ""
            if request.mobile_output_enabled:
                mobile_output_path = str(self._build_mobile_output_path(target_dir, target_filename))
            warnings = list(item.warnings)
            if write_mode == "CONFLICT":
                warnings.append("날짜 기준 고정 SEQ가 이미 사용 중인 파일과 충돌합니다.")
            preview_items.append(
                PreviewItem(
                    item_id=str(item.source_path),
                    media_type=item.media_type,
                    source_path=str(item.source_path),
                    target_directory=str(target_dir),
                    target_path=str(target_path),
                    new_filename=target_filename,
                    write_mode=write_mode,
                    captured_at=item.captured_at.isoformat(sep=" "),
                    datetime_source=item.datetime_source,
                    model_name=model_name,
                    model_source=item.model_source,
                    warnings=warnings,
                    metadata_entries=self._build_metadata_entries(item) + [
                        ("추출 모델명", model_name), ("파일명 적용 모델명", output_model_name),
                        ("분류 폴더 모델명", folder_model_name),
                    ],
                    mobile_output_enabled=request.mobile_output_enabled,
                    mobile_output_path=mobile_output_path,
                    output_model_name=output_model_name,
                    folder_model_name=folder_model_name,
                )
            )
            log_events.append(LogEvent(level="INFO", message="미리보기 생성", source_path=str(item.source_path), target_path=str(target_path)))
        return preview_items, error_items, log_events

    def _build_target_directory(self, target_root: Path, captured_at, model_name: str,
                                output_model_name: str | None = None) -> Path:
        day_dir = f"{captured_at:%Y%m%d}"
        model_dir = f"{day_dir}_{output_model_name if output_model_name is not None else sanitize_model_name(model_name)}"
        return target_root / f"{captured_at:%Y}년" / f"{captured_at:%Y}년 {captured_at:%m}월" / day_dir / model_dir

    def _build_target_filename(
        self,
        item: MediaItem,
        target_dir: Path,
        seq: int,
        allow_overwrite: bool = True,
        output_model_name: str | None = None,
        control=None,
    ) -> tuple[str, str]:
        captured_at = item.captured_at
        assert captured_at is not None
        model_name = output_model_name if output_model_name is not None else sanitize_model_name(item.model_name)
        prefix = f"{captured_at:%Y%m%d_%H%M%S}_{model_name}"
        ext = item.extension
        candidate = f"{prefix}_{seq:04d}{ext}"
        candidate_path = target_dir / candidate
        if candidate_path.exists():
            if allow_overwrite and self._can_overwrite(item, candidate_path, **({'control': control} if control else {})):
                return candidate, "OVERWRITE"
            return candidate, "CONFLICT"
        return candidate, "NEW"

    def _build_mobile_output_path(self, target_dir: Path, target_filename: str) -> Path:
        output_dir = target_dir / f"output_{target_dir.name}"
        source_suffix = Path(target_filename).suffix
        if source_suffix.lower() in {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".wmv"}:
            mobile_name = f"{Path(target_filename).stem}.mp4"
        elif source_suffix.lower() == ".heic":
            mobile_name = f"{Path(target_filename).stem}{self._jpg_suffix_for(source_suffix)}"
        else:
            mobile_name = target_filename
        return output_dir / mobile_name

    def _jpg_suffix_for(self, source_suffix: str) -> str:
        suffix_body = source_suffix[1:] if source_suffix.startswith(".") else source_suffix
        if suffix_body.isupper():
            return ".JPG"
        if suffix_body.islower():
            return ".jpg"
        return ".jpg"

    def _create_mobile_output(
        self,
        source_path: Path,
        target_path: Path,
        media_type: str,
        request: OrganizeRequest,
    ) -> str:
        if media_type == "video":
            from .video_output import clear_video_encoder_report
            clear_video_encoder_report()
        self._validate_mobile_output_limit(request)
        if request.mobile_output_limit_enabled:
            return self._create_size_limited_mobile_output(source_path, target_path, media_type, request)
        return self._convert_mobile_output(source_path, target_path, media_type, request)

    def _validate_mobile_output_limit(self, request: OrganizeRequest) -> None:
        if type(request.mobile_output_limit_enabled) is not bool:
            raise ValueError("출력 용량 제한 사용 여부는 참/거짓이어야 합니다.")
        if request.mobile_output_limit_enabled and (
                type(request.mobile_output_limit_mb) is not int
                or not 1 <= request.mobile_output_limit_mb <= 1000000):
            raise ValueError("출력 용량 제한은 1~1,000,000 MB의 정수로 설정해주세요.")

    def _create_size_limited_mobile_output(
        self, source_path: Path, target_path: Path, media_type: str,
        request: OrganizeRequest, exclusive: bool = False,
    ) -> str:
        if exclusive and (target_path.exists() or target_path.is_symlink()):
            raise FileExistsError("모바일 출력 파일이 이미 존재합니다.")
        # Stage outside output_: exclusion must not create an empty final folder.
        staging_parent = target_path.parent.parent
        while not staging_parent.exists():
            staging_parent = staging_parent.parent
        with tempfile.TemporaryDirectory(dir=staging_parent, prefix=".photoorganizer_") as temporary:
            staged = Path(temporary) / target_path.name
            status = self._convert_mobile_output(source_path, staged, media_type, request)
            # only_if_smaller SKIPPED takes precedence: no output was accepted.
            if status != "SUCCESS":
                return status
            if not staged.is_file():
                raise OSError("모바일 출력 성공 응답에 파일이 없습니다.")
            size = staged.stat().st_size
            if size >= request.mobile_output_limit_mb * 1000000:
                raise MobileOutputSizeExcluded(
                    f"출력 용량 제한으로 제외: 결과 {size / 1000000:.6f} MB ({size:,} 바이트) / "
                    f"기준 {request.mobile_output_limit_mb:,} MB 이상"
                )
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if exclusive:
                self._copy_exclusive(staged, target_path)
            else:
                os.replace(staged, target_path)
            return status

    def _convert_mobile_output(
        self, source_path: Path, target_path: Path, media_type: str, request: OrganizeRequest,
    ) -> str:
        if media_type == "video":
            video_options = {}
            encoder = getattr(request, "video_encoder", "cpu")
            speed = getattr(request, "conversion_speed", "balanced")
            if encoder != "cpu":
                video_options["encoder"] = encoder
            if speed != "balanced":
                video_options["speed"] = speed
            return create_mobile_video_output(
                source_path=source_path,
                target_path=target_path,
                max_width=request.mobile_output_video_max_width,
                quality=request.mobile_output_video_quality,
                only_if_smaller=request.mobile_output_video_only_if_smaller,
                **video_options,
            )
        photo_options = {}
        if getattr(request, "conversion_speed", "balanced") != "balanced":
            photo_options["speed"] = request.conversion_speed
        from .operation_control import current_control
        if current_control() is not None:
            from .isolated_work import isolated_call
            isolated_call('photo', (source_path, target_path, request.mobile_output_max_width,
                                   request.mobile_output_jpeg_quality,
                                   request.mobile_output_keep_smaller_original,
                                   getattr(request, 'conversion_speed', 'balanced')))
            return 'SUCCESS'
        self._create_photo_mobile_output(
            source_path=source_path,
            target_path=target_path,
            max_width=request.mobile_output_max_width,
            jpeg_quality=request.mobile_output_jpeg_quality,
            keep_smaller_original=request.mobile_output_keep_smaller_original,
            **photo_options,
        )
        return "SUCCESS"

    def _create_photo_mobile_output(
        self,
        source_path: Path,
        target_path: Path,
        max_width: int,
        jpeg_quality: int,
        keep_smaller_original: bool,
        speed: str = "balanced",
    ) -> None:
        if Image is None:
            raise RuntimeError("Pillow가 설치되어 있지 않아 모바일 출력을 생성할 수 없습니다.")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source_path) as image:
            exif_bytes = self._extract_exif_bytes(image)
            icc_profile = image.info.get("icc_profile")
            pnginfo = self._extract_pnginfo(image)
            image.load()
            working = image.copy()
        if working.mode not in ("RGB", "RGBA", "L"):
            working = working.convert("RGB")
        if working.width > max_width:
            new_height = max(1, int(round(working.height * (max_width / working.width))))
            working = working.resize((max_width, new_height), Image.Resampling.LANCZOS, reducing_gap=3.0)
        elif not keep_smaller_original and working.width != max_width:
            new_height = max(1, int(round(working.height * (max_width / working.width))))
            working = working.resize((max_width, new_height), Image.Resampling.LANCZOS)
        suffix = target_path.suffix.lower()
        save_kwargs: dict[str, object] = {}
        if suffix in {".jpg", ".jpeg"}:
            if working.mode in ("RGBA", "LA"):
                background = Image.new("RGB", working.size, (255, 255, 255))
                background.paste(working, mask=working.getchannel("A"))
                working = background
            elif working.mode != "RGB":
                working = working.convert("RGB")
            save_kwargs = {"format": "JPEG", "quality": jpeg_quality, "optimize": speed != "fast"}
            if exif_bytes:
                save_kwargs["exif"] = exif_bytes
            if icc_profile:
                save_kwargs["icc_profile"] = icc_profile
        elif suffix == ".png":
            save_kwargs = {"format": "PNG", "optimize": speed != "fast", "compress_level": 6 if speed == "fast" else 9}
            if pnginfo is not None:
                save_kwargs["pnginfo"] = pnginfo
            if exif_bytes:
                save_kwargs["exif"] = exif_bytes
            if icc_profile:
                save_kwargs["icc_profile"] = icc_profile
        else:
            if working.mode in ("RGBA", "LA"):
                background = Image.new("RGB", working.size, (255, 255, 255))
                background.paste(working, mask=working.getchannel("A"))
                working = background
            elif working.mode != "RGB":
                working = working.convert("RGB")
            save_kwargs = {"format": "JPEG", "quality": jpeg_quality, "optimize": speed != "fast"}
            if exif_bytes:
                save_kwargs["exif"] = exif_bytes
            if icc_profile:
                save_kwargs["icc_profile"] = icc_profile
        working.save(target_path, **save_kwargs)

    def _extract_exif_bytes(self, image) -> bytes | None:
        try:
            exif = image.getexif()
        except Exception:
            exif = None
        if exif:
            try:
                exif_bytes = exif.tobytes()
                if exif_bytes:
                    return exif_bytes
            except Exception:
                pass
        raw_exif = image.info.get("exif")
        if isinstance(raw_exif, bytes) and raw_exif:
            return raw_exif
        return None

    def _extract_pnginfo(self, image):
        if PngImagePlugin is None:
            return None
        text_keys = {
            key: value
            for key, value in image.info.items()
            if isinstance(value, str) and key not in {"exif", "icc_profile"}
        }
        if not text_keys:
            return None
        pnginfo = PngImagePlugin.PngInfo()
        for key, value in text_keys.items():
            pnginfo.add_text(key, value)
        return pnginfo

    def _next_sequence_for_directory(self, target_dir: Path, sequence_counters: dict[Path, int] | None = None) -> int:
        if sequence_counters is None:
            return 1
        return sequence_counters.get(target_dir, 1)

    def _remember_next_sequence(
        self,
        target_dir: Path,
        next_seq: int,
        sequence_counters: dict[Path, int] | None = None,
    ) -> None:
        if sequence_counters is None:
            return
        current = sequence_counters.get(target_dir, 1)
        sequence_counters[target_dir] = max(current, next_seq)

    def _can_overwrite(self, source_item: MediaItem, target_path: Path, control=None) -> bool:
        if not target_path.is_file():
            return False
        if source_item.extension.lower() != target_path.suffix.lower():
            return False
        try:
            source_size = source_item.source_path.stat().st_size
            target_size = target_path.stat().st_size
        except OSError:
            return False
        if source_size != target_size:
            return False
        source_metadata = source_item.metadata.get("source_metadata")
        if not source_metadata:
            return False
        try:
            if control is not None and self._native_extractor():
                from .isolated_work import isolated_call
                from .operation_control import OperationInterrupted
                while True:
                    self._preview_checkpoint(control)
                    try:
                        with control.file_activity(str(target_path), target_path, 'metadata'):
                            target_item = isolated_call('metadata', (target_path,))
                        break
                    except OperationInterrupted:
                        self._preview_checkpoint(control)
            else:
                target_item = self.extractor.extract(target_path)
        except Exception:
            from .operation_control import OperationStopped
            if control is not None and control.stop_requested:
                raise OperationStopped()
            return False
        target_metadata = target_item.metadata.get("source_metadata")
        if not target_metadata:
            return False
        return source_metadata == target_metadata

    def _build_metadata_entries(self, item: MediaItem) -> list[tuple[str, str]]:
        entries: list[tuple[str, str]] = []
        media_info = item.metadata.get("media_info", {})
        display_metadata = item.metadata.get("display_metadata", {})
        source_metadata = item.metadata.get("source_metadata", {})
        file_size = self._safe_file_size(item.source_path)

        entries.append(("미디어 종류", "사진" if item.media_type == "photo" else "영상"))
        entries.append(("확장자", item.extension or "-"))
        entries.append(("파일 크기", self._format_file_size(file_size) if file_size is not None else "-"))
        resolution = self._format_resolution(media_info)
        if resolution:
            entries.append(("원본 크기", resolution))
        entries.append(("추출된 촬영/생성 일시", item.captured_at.strftime("%Y-%m-%d %H:%M:%S") if item.captured_at else "-"))
        entries.append(("추출된 모델명", sanitize_model_name(item.model_name)))
        entries.append(("일시 출처", item.datetime_source or "-"))
        entries.append(("모델명 출처", item.model_source or "-"))
        self._append_if_present(entries, "파일명 모델명 안내", item.metadata.get("filename_model_notice"))
        entries.append(("메타 추출 도구", self._format_metadata_tools(source_metadata, item)))

        if item.media_type == "photo":
            self._append_if_present(entries, "EXIF Make", display_metadata.get("photo_make"))
            self._append_if_present(entries, "EXIF Model", display_metadata.get("photo_model"))
            self._append_if_present(entries, "EXIF DateTimeOriginal", display_metadata.get("photo_datetime_original"))
            self._append_if_present(entries, "EXIF DateTimeDigitized", display_metadata.get("photo_datetime_digitized"))
            self._append_if_present(entries, "Orientation", display_metadata.get("photo_orientation"))
        else:
            lookup = item.metadata.get("video_model_lookup", {})
            status_labels = {"found": "영상 메타에서 모델명 확인", "not_found": "지원 태그에서 모델명 미확인", "failed": "영상 메타 조회 실패"}
            entries.append(("영상 모델 조회", status_labels.get(lookup.get("status"), "조회 상태 미기록")))
            self._append_if_present(entries, "영상 원본 모델명", lookup.get("model"))
            tool_labels = {"success": "조회 성공", "error": "조회 실패", "unavailable": "도구 사용 불가", "not_needed": "보조 조회 불필요"}
            for tool, result in lookup.get("tools", {}).items():
                text = tool_labels.get(result.get("status"), "미확인")
                if result.get("detail"):
                    text += f": {result['detail']}"
                entries.append((f"{tool} 조회", text))
            inference = item.metadata.get("model_inference", {})
            if inference.get("status") == "found":
                scope = "앞뒤 사진 보완: 시간 제한 없음" if inference.get("mode") == "unbounded_photos" else f"±{inference['window_minutes']}분"
                entries.append(("모델명 보완", f"{inference['candidate']} / {inference['delta_seconds']:g}초 차이 / {scope}"))
            elif inference.get("detail"):
                entries.append(("모델명 보완", str(inference["detail"])))
            self._append_if_present(entries, "생성 시각 메타", display_metadata.get("video_creation_time"))
            self._append_if_present(entries, "Video Codec", media_info.get("video_codec"))
            self._append_if_present(entries, "Audio Codec", media_info.get("audio_codec"))
            self._append_if_present(entries, "Duration", self._format_duration(media_info.get("duration_seconds")))
            self._append_if_present(entries, "Frame Rate", media_info.get("frame_rate"))

        return [(label, value if value not in ("", None) else "-") for label, value in entries]

    def _append_if_present(self, entries: list[tuple[str, str]], label: str, value: object) -> None:
        if value in (None, ""):
            return
        entries.append((label, str(value)))

    def _safe_file_size(self, path: Path) -> int | None:
        try:
            return path.stat().st_size
        except OSError:
            return None

    def _format_file_size(self, size: int) -> str:
        units = ["B", "KB", "MB", "GB", "TB"]
        value = float(size)
        unit = units[0]
        for candidate in units:
            unit = candidate
            if value < 1024 or candidate == units[-1]:
                break
            value /= 1024
        if unit == "B":
            return f"{int(value)} {unit}"
        return f"{value:.1f} {unit}"

    def _format_resolution(self, media_info: object) -> str | None:
        if not isinstance(media_info, dict):
            return None
        width = media_info.get("width")
        height = media_info.get("height")
        if width in (None, "") or height in (None, ""):
            return None
        return f"{width} x {height}"

    def _format_metadata_tools(self, source_metadata: object, item: MediaItem) -> str:
        if not isinstance(source_metadata, dict):
            return "파일명 fallback" if item.metadata.get("filename_pattern") else "-"
        tool_map = {
            "exifread": "exifread",
            "pillow": "Pillow",
            "ffprobe": "ffprobe",
            "mediainfo": "pymediainfo",
        }
        tools = [tool_map.get(key, key) for key in source_metadata.keys()]
        if item.metadata.get("filename_pattern"):
            tools.append("파일명 fallback")
        return ", ".join(tools) if tools else "-"

    def _format_duration(self, raw_seconds: object) -> str | None:
        if raw_seconds in (None, ""):
            return None
        try:
            total_seconds = float(str(raw_seconds))
        except (TypeError, ValueError):
            return str(raw_seconds)
        minutes, seconds = divmod(int(round(total_seconds)), 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _move_to_recycle_bin(self, path: Path) -> None:
        if send2trash is not None:
            send2trash(str(path))
            return
        from ctypes import wintypes

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("wFunc", wintypes.UINT),
                ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR),
                ("fFlags", ctypes.c_ushort),
                ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", wintypes.LPVOID),
                ("lpszProgressTitle", wintypes.LPCWSTR),
            ]

        operation = SHFILEOPSTRUCTW()
        operation.wFunc = 3
        operation.pFrom = str(path) + "\0\0"
        operation.fFlags = 0x0040 | 0x0010 | 0x0400
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
        if result != 0:
            raise OSError(f"휴지통 이동 실패: {result}")

    def _report_progress(
        self,
        progress_callback: Callable[[str, int, int], None] | None,
        message: str,
        current: int,
        total: int,
    ) -> None:
        if progress_callback is not None:
            progress_callback(message, current, total)


def human_reason(preview_item: PreviewItem) -> str:
    parts = [preview_item.datetime_source, preview_item.model_source]
    return " / ".join(part for part in parts if part and part != "UNKNOWN") or "UNKNOWN"
