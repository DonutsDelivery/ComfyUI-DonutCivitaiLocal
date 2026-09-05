"""Port of DonutNodes PR #25 to the standalone CivitAI companion package.

The original contribution targeted the CivitAI browser/downloader while those
files still lived in ComfyUI-DonutNodes. They now live in
ComfyUI-DonutCivitaiLocal. This module layers the contribution onto the newer
hardened requests-based transport instead of restoring the older urllib path.

Features:
- physical diffusion_models destination for CivitAI Checkpoint downloads
- safe user-selectable subfolders under the appropriate model root
- folder-list + advanced-download routes used by the browser enhancement
- aria2c acceleration when installed, with RPC progress/cancellation
- fallback to the package's existing downloader when aria2c is unavailable
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional

import requests
from aiohttp import web

from . import civitai_download
from .civitai_transport import civitai_request
from .config import load_config

try:
    import folder_paths
    HAS_FOLDER_PATHS = True
except ImportError:
    folder_paths = None
    HAS_FOLDER_PATHS = False

try:
    from server import PromptServer
    HAS_SERVER = True
except ImportError:
    PromptServer = None
    HAS_SERVER = False


_ORIGINAL_DOWNLOAD_THREAD = civitai_download.CivitAIDownloader._download_thread
_INSTALLED = False
_ROUTES_REGISTERED = False


def get_model_root(model_type: str) -> str:
    """Return the model-category root, preserving a physical checkpoint folder."""
    if model_type == "Checkpoint" and HAS_FOLDER_PATHS:
        # ComfyUI may alias diffusion_models to another logical folder. PR #25
        # intentionally targeted the physical directory for RunPod/new layouts.
        return os.path.abspath(os.path.join(folder_paths.models_dir, "diffusion_models"))
    return os.path.abspath(civitai_download.get_model_folder(model_type))


def _safe_filename(filename: str) -> str:
    if not filename:
        return "model.safetensors"
    if os.path.isabs(filename) or Path(filename).name != filename:
        raise ValueError("Download filename must not contain a path")
    return filename


def get_selected_download_path(
    model_type: str,
    base_model: str,
    filename: str,
    selected_folder: Optional[str] = None,
) -> str:
    """Resolve an optional browser-selected folder without escaping its root."""
    filename = _safe_filename(filename)
    base_dir = get_model_root(model_type)

    if selected_folder is None:
        # Preserve the existing automatic LoRA organization when the user has
        # not explicitly selected a folder.
        if model_type in ("LORA", "LoCon", "DoRA"):
            subfolder = civitai_download.normalize_base_model(base_model)
            full_dir = os.path.join(base_dir, subfolder) if subfolder else base_dir
        else:
            full_dir = base_dir
    else:
        if not isinstance(selected_folder, str):
            raise ValueError("Selected download folder must be a string")
        if os.path.isabs(selected_folder):
            raise ValueError("Selected download folder must be relative")

        normalized = os.path.normpath(selected_folder)
        if normalized in ("", "."):
            full_dir = base_dir
        else:
            full_dir = os.path.abspath(os.path.join(base_dir, normalized))
            try:
                common = os.path.commonpath([base_dir, full_dir])
            except ValueError as exc:
                raise ValueError("Selected download folder is outside the model directory") from exc
            if common != base_dir:
                raise ValueError("Selected download folder is outside the model directory")

    Path(full_dir).mkdir(parents=True, exist_ok=True)
    return os.path.join(full_dir, filename)


def list_download_folders(model_type: str, base_model: str = "") -> dict:
    """Return browser choices relative to the model category's root."""
    base_dir = get_model_root(model_type)
    root_name = os.path.basename(base_dir.rstrip(os.sep)) or "models"
    folders = {""}

    if os.path.isdir(base_dir):
        for root, dirs, _files in os.walk(base_dir, followlinks=False):
            for directory in dirs:
                full_path = os.path.join(root, directory)
                rel = os.path.relpath(full_path, base_dir).replace(os.sep, "/")
                if rel not in ("", ".") and not rel.startswith("../"):
                    folders.add(rel)

    default_folder = ""
    if model_type in ("LORA", "LoCon", "DoRA"):
        default_folder = civitai_download.normalize_base_model(base_model)
        if default_folder:
            folders.add(default_folder)

    ordered = sorted(folders, key=lambda value: (value != "", value.lower()))
    return {
        "rootName": root_name,
        "defaultFolder": default_folder,
        "folders": [
            {
                "value": value,
                "label": root_name if not value else f"{root_name}/{value}",
            }
            for value in ordered
        ],
    }


def _aria2_rpc(url: str, secret: str, request_id: str, method: str, params=None):
    rpc_params = [f"token:{secret}"]
    if params:
        rpc_params.extend(params)
    response = requests.post(
        url,
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": rpc_params,
        },
        timeout=2,
    )
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        raise RuntimeError(f"aria2 RPC error: {data['error']}")
    return data.get("result")


def _aria2_download_thread(
    self,
    download_id: str,
    url: str,
    save_path: str,
    api_key: Optional[str],
    on_progress,
    model_type: str = "",
    sha256: Optional[str] = None,
):
    """Use aria2c when available; otherwise keep the current downloader path."""
    aria2_path = shutil.which("aria2c")
    if not aria2_path:
        return _ORIGINAL_DOWNLOAD_THREAD(
            self, download_id, url, save_path, api_key, on_progress, model_type, sha256
        )

    status = self.downloads.get(download_id)
    if status is None:
        return

    download_url = url
    if api_key:
        separator = "&" if "?" in url else "?"
        download_url = f"{url}{separator}token={api_key}"

    headers = {"User-Agent": "ComfyUI-DonutCivitaiLocal/1.0"}
    process = None
    rpc_url = None
    rpc_secret = None

    try:
        with self._lock:
            status.status = "downloading"

        Path(save_path).parent.mkdir(parents=True, exist_ok=True)

        # Preserve the hardened transport's origin + redirect validation. We only
        # hand aria2 a URL that the current CivitAI transport has already accepted.
        with civitai_request(
            "GET", download_url, headers=headers, timeout=30, stream=True
        ) as response:
            response.raise_for_status()
            resolved_url = response.url
            resolved_size = int(response.headers.get("Content-Length", 0) or 0)

        with self._lock:
            if resolved_size > 0:
                status.total_size = resolved_size

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            rpc_port = sock.getsockname()[1]

        rpc_secret = uuid.uuid4().hex
        rpc_url = f"http://127.0.0.1:{rpc_port}/jsonrpc"
        save_directory = str(Path(save_path).parent)
        save_filename = Path(save_path).name

        command = [
            aria2_path,
            "--continue=true",
            "--max-connection-per-server=16",
            "--split=16",
            "--min-split-size=4M",
            "--file-allocation=none",
            "--allow-overwrite=true",
            "--auto-file-renaming=false",
            "--console-log-level=warn",
            "--summary-interval=0",
            "--enable-rpc=true",
            "--rpc-listen-all=false",
            f"--rpc-listen-port={rpc_port}",
            f"--rpc-secret={rpc_secret}",
            "--user-agent=ComfyUI-DonutCivitaiLocal/1.0",
            "--dir", save_directory,
            "--out", save_filename,
            resolved_url,
        ]

        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        stat_keys = [
            "completedLength",
            "totalLength",
            "downloadSpeed",
            "status",
            "errorCode",
            "errorMessage",
        ]
        aria2_finished = False

        while process.poll() is None:
            with self._lock:
                cancelled = status.status == "cancelled"

            if cancelled:
                try:
                    _aria2_rpc(rpc_url, rpc_secret, download_id, "aria2.forceShutdown")
                except Exception:
                    process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

                for partial in (save_path, save_path + ".aria2"):
                    try:
                        if os.path.exists(partial):
                            os.remove(partial)
                    except OSError:
                        pass
                return

            aria2_status = None
            try:
                active = _aria2_rpc(
                    rpc_url, rpc_secret, download_id, "aria2.tellActive", [stat_keys]
                )
                if active:
                    aria2_status = active[0]
                else:
                    waiting = _aria2_rpc(
                        rpc_url,
                        rpc_secret,
                        download_id,
                        "aria2.tellWaiting",
                        [0, 1, stat_keys],
                    )
                    if waiting:
                        aria2_status = waiting[0]
                    else:
                        stopped = _aria2_rpc(
                            rpc_url,
                            rpc_secret,
                            download_id,
                            "aria2.tellStopped",
                            [-1, 1, stat_keys],
                        )
                        if stopped:
                            aria2_status = stopped[0]
            except Exception:
                # aria2's RPC listener can take a short moment to become ready.
                aria2_status = None

            if aria2_status:
                state = aria2_status.get("status", "")
                completed = int(aria2_status.get("completedLength", 0) or 0)
                total = int(aria2_status.get("totalLength", 0) or 0)
                speed = float(aria2_status.get("downloadSpeed", 0) or 0)

                with self._lock:
                    status.downloaded_size = completed
                    status.speed_bps = speed
                    if total > 0:
                        status.total_size = total

                if on_progress:
                    on_progress(status)

                if state == "complete":
                    aria2_finished = True
                    try:
                        _aria2_rpc(rpc_url, rpc_secret, download_id, "aria2.shutdown")
                    except Exception:
                        process.terminate()
                    break

                if state in ("error", "removed"):
                    code = aria2_status.get("errorCode", "")
                    message = aria2_status.get("errorMessage", "Unknown aria2 error")
                    raise RuntimeError(f"aria2 download failed ({code}): {message}")

            time.sleep(0.5)

        if aria2_finished and process.poll() is None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

        if process.returncode not in (0, None):
            raise RuntimeError(f"aria2c exited with error code {process.returncode}")

        final_size = os.path.getsize(save_path) if os.path.exists(save_path) else 0
        if final_size <= 0:
            raise RuntimeError("aria2c completed without producing the requested file")

        with self._lock:
            status.downloaded_size = final_size
            status.total_size = final_size
            status.speed_bps = 0.0
            status.status = "completed"
            status.completed_at = civitai_download.datetime.now().isoformat()

        if on_progress:
            on_progress(status)

        if sha256:
            self._save_hash_file(save_path, sha256)

        folder_name = civitai_download.MODEL_TYPE_TO_FOLDER.get(model_type, "loras")
        civitai_download.invalidate_folder_cache(folder_name)

    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else 0
        with self._lock:
            status.status = "error"
            status.error = f"HTTP {status_code}: {exc}"
    except Exception as exc:
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except Exception:
                pass
        with self._lock:
            if status.status != "cancelled":
                status.status = "error"
                status.error = str(exc)
        print(f"[CivitAI Download] aria2 error: {exc}")


def install_aria2_patch():
    global _INSTALLED
    if _INSTALLED:
        return
    civitai_download.CivitAIDownloader._download_thread = _aria2_download_thread
    _INSTALLED = True


def register_routes():
    """Register the relocated PR #25 endpoints without changing legacy routes."""
    global _ROUTES_REGISTERED
    if _ROUTES_REGISTERED or not HAS_SERVER:
        return

    # Import after shared/server_routes has initialized to avoid circular import.
    from . import server_routes

    routes = PromptServer.instance.routes

    @routes.get('/donut/civitai/download/folders')
    async def civitai_download_folders(request):
        try:
            model_type = request.query.get("modelType", "LORA")
            base_model = request.query.get("baseModel", "")
            return web.json_response(list_download_folders(model_type, base_model))
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=500)

    @routes.post('/donut/civitai/download/advanced')
    async def civitai_download_advanced(request):
        try:
            data = await request.json()
            download_url = data.get("downloadUrl")
            model_type = data.get("modelType", "LORA")
            base_model = data.get("baseModel", "")
            filename = data.get("filename", "model.safetensors")
            sha256 = data.get("sha256")
            selected_folder = data.get("selectedFolder", None)
            skip_duplicate_check = data.get("skipDuplicateCheck", False)

            if not download_url:
                return web.json_response({"error": "No download URL provided"}, status=400)

            if sha256 and not skip_duplicate_check:
                existing = server_routes.find_file_by_hash(sha256)
                if existing.get("found"):
                    return web.json_response({
                        "error": "duplicate",
                        "message": f"File already exists: {existing['filename']}",
                        "existingFile": existing["filename"],
                        "existingPath": existing["full_path"],
                        "folderType": existing["folder_type"],
                    }, status=409)

            save_path = get_selected_download_path(
                model_type,
                base_model,
                filename,
                selected_folder=selected_folder,
            )

            config = load_config(force_reload=True)
            api_key = config.get("civitai", {}).get("api_key")
            downloader = civitai_download.get_downloader()
            download_id = downloader.start_download(
                download_url=download_url,
                save_path=save_path,
                api_key=api_key,
                model_type=model_type,
                sha256=sha256,
            )

            return web.json_response({
                "downloadId": download_id,
                "savePath": save_path,
                "status": "started",
            })
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=500)

    _ROUTES_REGISTERED = True


install_aria2_patch()
register_routes()
