import { api } from "../../scripts/api.js";
import { DonutCivitaiBrowser } from "./donut_civitai_browser.js";

/**
 * Port of ComfyUI-DonutNodes PR #25 to ComfyUI-DonutCivitaiLocal.
 *
 * The main browser has continued evolving since the original PR. Rather than
 * replacing that large file with an older fork snapshot, this enhancement
 * patches the current browser prototype with the contributed multi-file and
 * download-folder behavior.
 */

const proto = DonutCivitaiBrowser?.prototype;

if (proto && !proto.__donutPr25PortInstalled) {
    proto.__donutPr25PortInstalled = true;

    const originalRenderDetailView = proto.renderDetailView;
    const originalGetExpectedPath = proto.getExpectedPath;

    proto.getSelectedCivitaiFile = function(modelVersion) {
        const select = document.getElementById("donut-civitai-file");
        const index = select ? Number.parseInt(select.value || "0", 10) : 0;
        return modelVersion?.files?.[Number.isFinite(index) ? index : 0]
            || modelVersion?.files?.[0]
            || null;
    };

    proto._pr25SelectedVersion = function() {
        const model = this.currentModel;
        if (!model?.modelVersions?.length) return null;
        const select = document.getElementById("donut-civitai-version");
        const index = select ? Number.parseInt(select.value || "0", 10) : 0;
        return model.modelVersions[Number.isFinite(index) ? index : 0]
            || model.modelVersions[0];
    };

    proto._pr25UpdatePathPreview = function(modelVersion) {
        const path = document.getElementById("donut-civitai-save-path");
        const folder = document.getElementById("donut-civitai-folder");
        const file = this.getSelectedCivitaiFile(modelVersion);
        if (!path || !file) return;

        if (folder?.dataset?.rootName && !folder.disabled) {
            const selected = folder.value || "";
            const folderPart = selected ? `/${selected}` : "";
            path.textContent = `Will save to: models/${folder.dataset.rootName}${folderPart}/${file.name}`;
        } else {
            path.textContent = `Will save to: ${this.getExpectedPath(
                this.currentModel?.type,
                modelVersion?.baseModel,
                file.name,
            )}`;
        }
    };

    proto._pr25RefreshSelectedFileUI = function(modelVersion, downloadSection) {
        const file = this.getSelectedCivitaiFile(modelVersion);
        if (!file || !downloadSection) return;

        // Update the existing file-info row from the current browser.
        const fileInfo = Array.from(downloadSection.children).find((element) => {
            if (!(element instanceof HTMLElement) || element.tagName !== "DIV") return false;
            return element.style.display === "flex" && element.querySelectorAll("span").length >= 2;
        });
        if (fileInfo) {
            const spans = fileInfo.querySelectorAll("span");
            if (spans[0]) spans[0].textContent = file.name;
            if (spans[1]) spans[1].textContent = this.formatBytes((file.sizeKB || 0) * 1024);
        }

        const sha = file.hashes?.SHA256;
        const selectedDownloaded = !!(
            sha && this.localHashes?.has?.(sha.toUpperCase())
        );

        // The base browser labels slot buttons by version-level downloaded state.
        // Re-label them for the selected file so BF16/FP8 variants do not lie.
        for (let slot = 1; slot <= 3; slot++) {
            const button = Array.from(downloadSection.querySelectorAll("button")).find(
                (candidate) => candidate.textContent?.includes(`Slot ${slot}`),
            );
            if (button) {
                button.innerHTML = selectedDownloaded ? `→ Slot ${slot}` : `↓ Slot ${slot}`;
            }
        }

        const deleteButton = Array.from(downloadSection.querySelectorAll("button")).find(
            (candidate) => candidate.textContent?.includes("Delete from disk"),
        );
        if (deleteButton) {
            deleteButton.style.display = selectedDownloaded ? "block" : "none";
        }

        this._pr25UpdatePathPreview(modelVersion);
    };

    proto._pr25BindActionButtons = function(modelVersion, downloadSection) {
        const model = this.currentModel;
        if (!model || !modelVersion || !downloadSection) return;

        for (let slot = 1; slot <= 3; slot++) {
            const button = Array.from(downloadSection.querySelectorAll("button")).find(
                (candidate) => candidate.textContent?.includes(`Slot ${slot}`),
            );
            if (!button) continue;

            button.onclick = () => {
                const selectedVersion = this._pr25SelectedVersion() || modelVersion;
                const selectedFile = this.getSelectedCivitaiFile(selectedVersion);
                const sha = selectedFile?.hashes?.SHA256;
                const selectedDownloaded = !!(
                    sha && this.localHashes?.has?.(sha.toUpperCase())
                );

                if (selectedDownloaded && sha) {
                    this.loadDownloadedToSlot(sha, slot, model.name, {
                        url: selectedFile.downloadUrl || selectedVersion.downloadUrl,
                        filename: selectedFile.name,
                        modelType: model.type,
                        baseModel: selectedVersion.baseModel,
                    });
                } else {
                    this.startDownload(selectedVersion, slot, button, selectedFile);
                }
            };
        }

        const deleteButton = Array.from(downloadSection.querySelectorAll("button")).find(
            (candidate) => candidate.textContent?.includes("Delete from disk"),
        );
        if (deleteButton) {
            deleteButton.onclick = () => {
                const selectedVersion = this._pr25SelectedVersion() || modelVersion;
                const selectedFile = this.getSelectedCivitaiFile(selectedVersion);
                const sha = selectedFile?.hashes?.SHA256;
                if (sha) this.deleteLora(sha, model.name);
            };
        }

        const downloadButton = Array.from(downloadSection.querySelectorAll("button")).find(
            (candidate) => candidate.textContent?.includes("Download Only"),
        );
        if (downloadButton) {
            downloadButton.onclick = () => {
                const selectedVersion = this._pr25SelectedVersion() || modelVersion;
                this.startDownload(
                    selectedVersion,
                    null,
                    downloadButton,
                    this.getSelectedCivitaiFile(selectedVersion),
                );
            };
        }
    };

    proto._pr25PopulateFileDropdown = function(modelVersion, downloadSection) {
        const select = document.getElementById("donut-civitai-file");
        if (!select || !modelVersion) return;

        select.innerHTML = "";
        const files = modelVersion.files || [];
        if (!files.length) {
            const option = document.createElement("option");
            option.value = "0";
            option.textContent = "No files found";
            select.appendChild(option);
            select.disabled = true;
            return;
        }

        select.disabled = false;
        files.forEach((file, index) => {
            const option = document.createElement("option");
            option.value = String(index);
            const size = file.sizeKB
                ? ` - ${(file.sizeKB / 1024 / 1024).toFixed(2)} GB`
                : "";
            const precision = file.metadata?.fp
                || file.metadata?.format
                || file.type
                || "";
            option.textContent = `${file.name}${precision ? ` - ${precision}` : ""}${size}`;
            select.appendChild(option);
        });

        select.onchange = () => {
            this._pr25BindActionButtons(modelVersion, downloadSection);
            this._pr25RefreshSelectedFileUI(modelVersion, downloadSection);
        };
        this._pr25RefreshSelectedFileUI(modelVersion, downloadSection);
    };

    proto._pr25PopulateFolderDropdown = async function(modelVersion) {
        const select = document.getElementById("donut-civitai-folder");
        if (!select || !modelVersion || !this.currentModel) return;

        const params = new URLSearchParams({
            modelType: this.currentModel.type,
            baseModel: modelVersion.baseModel || "",
        });
        select.disabled = true;

        try {
            const response = await api.fetchApi(
                `/donut/civitai/download/folders?${params.toString()}`,
            );
            if (!response.ok) throw new Error(await response.text());
            const data = await response.json();

            select.innerHTML = "";
            select.dataset.rootName = data.rootName || "models";
            for (const folder of data.folders || []) {
                const option = document.createElement("option");
                option.value = folder.value;
                option.textContent = folder.label;
                option.selected = folder.value === (data.defaultFolder || "");
                select.appendChild(option);
            }
            select.disabled = false;
            select.onchange = () => this._pr25UpdatePathPreview(modelVersion);
            this._pr25UpdatePathPreview(modelVersion);
        } catch (error) {
            console.error("[CivitAI Browser] Could not load download folders:", error);
            select.innerHTML = "";
            const option = document.createElement("option");
            option.value = "";
            option.textContent = "Default folder";
            select.appendChild(option);
            select.disabled = true;
            this._pr25UpdatePathPreview(modelVersion);
        }
    };

    proto._pr25EnhanceDetailView = function() {
        const model = this.currentModel;
        if (!model?.modelVersions?.length) return;

        const versionSelect = document.getElementById("donut-civitai-version");
        const version = this._pr25SelectedVersion() || model.modelVersions[0];

        const downloadButton = Array.from(
            this.dialog?.querySelectorAll?.("button") || [],
        ).find((button) => button.textContent?.includes("Download Only"));
        const downloadSection = downloadButton?.parentElement;
        if (!downloadSection) return;

        let savePath = Array.from(downloadSection.children).find(
            (element) => element.textContent?.startsWith?.("Will save to:"),
        );
        if (savePath) savePath.id = "donut-civitai-save-path";

        if (!document.getElementById("donut-civitai-file")) {
            const section = document.createElement("div");
            section.id = "donut-civitai-file-section";
            section.style.cssText = "margin-bottom: 20px;";
            const label = document.createElement("div");
            label.textContent = "File";
            label.style.cssText = "font-size: 12px; font-weight: 600; color: #888; text-transform: uppercase; margin-bottom: 8px;";
            const select = document.createElement("select");
            select.id = "donut-civitai-file";
            select.style.cssText = "width: 100%; padding: 10px; background: #0d0d1a; border: 1px solid #333; border-radius: 6px; color: #eee; font-size: 14px; cursor: pointer;";
            section.append(label, select);

            const versionSection = versionSelect?.parentElement;
            if (versionSection?.parentElement) {
                versionSection.insertAdjacentElement("afterend", section);
            } else {
                downloadSection.parentElement?.insertBefore(section, downloadSection);
            }
        }

        if (!document.getElementById("donut-civitai-folder")) {
            const section = document.createElement("div");
            section.id = "donut-civitai-folder-section";
            section.style.cssText = "margin-bottom: 12px;";
            const label = document.createElement("div");
            label.textContent = "Folder";
            label.style.cssText = "font-size: 12px; font-weight: 600; color: #888; text-transform: uppercase; margin-bottom: 8px;";
            const select = document.createElement("select");
            select.id = "donut-civitai-folder";
            select.disabled = true;
            select.style.cssText = "width: 100%; padding: 10px; background: #0d0d1a; border: 1px solid #333; border-radius: 6px; color: #eee; font-size: 13px; cursor: pointer;";
            const option = document.createElement("option");
            option.value = "";
            option.textContent = "Loading folders...";
            select.appendChild(option);
            section.append(label, select);
            downloadSection.insertBefore(section, downloadButton);
        }

        if (versionSelect && !versionSelect.__donutPr25Bound) {
            versionSelect.__donutPr25Bound = true;
            const previous = versionSelect.onchange;
            versionSelect.onchange = async (event) => {
                if (typeof previous === "function") previous.call(versionSelect, event);
                const selectedVersion = this._pr25SelectedVersion();
                if (!selectedVersion) return;
                this._pr25PopulateFileDropdown(selectedVersion, downloadSection);
                await this._pr25PopulateFolderDropdown(selectedVersion);
                this._pr25BindActionButtons(selectedVersion, downloadSection);
            };
        }

        this._pr25PopulateFileDropdown(version, downloadSection);
        this._pr25PopulateFolderDropdown(version);
        this._pr25BindActionButtons(version, downloadSection);
    };

    proto.renderDetailView = function(...args) {
        const result = originalRenderDetailView.apply(this, args);
        // renderDetailView is synchronous today; queueing also keeps the patch
        // safe if later browser code appends a final DOM element after return.
        queueMicrotask(() => this._pr25EnhanceDetailView());
        return result;
    };

    proto.startDownload = async function(
        modelVersion,
        loadToSlot = null,
        buttonElement = null,
        selectedFile = null,
    ) {
        const model = this.currentModel;
        if (!model || !modelVersion) return;

        const file = selectedFile || this.getSelectedCivitaiFile(modelVersion);
        if (!file) {
            alert("No downloadable file found");
            return;
        }

        if (buttonElement) {
            buttonElement.disabled = true;
            buttonElement.dataset.originalText = buttonElement.innerHTML;
            buttonElement.dataset.originalBg = buttonElement.style.background;
            buttonElement.innerHTML = `<span class="donut-dl-text">Starting...</span>`;
            buttonElement.style.background = "#555";
            buttonElement.style.position = "relative";
            buttonElement.style.overflow = "hidden";

            const progressBar = document.createElement("div");
            progressBar.className = "donut-dl-progress";
            progressBar.style.cssText = "position:absolute;left:0;top:0;height:100%;width:0%;background:rgba(90,140,90,.5);transition:width .3s;z-index:0;";
            buttonElement.insertBefore(progressBar, buttonElement.firstChild);
            const textSpan = buttonElement.querySelector(".donut-dl-text");
            if (textSpan) textSpan.style.cssText = "position: relative; z-index: 1;";
        }

        const folderSelect = document.getElementById("donut-civitai-folder");
        const selectedFolder = folderSelect && !folderSelect.disabled
            ? folderSelect.value
            : null;

        try {
            const response = await api.fetchApi("/donut/civitai/download/advanced", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    downloadUrl: file.downloadUrl,
                    modelType: model.type,
                    baseModel: modelVersion.baseModel,
                    filename: file.name,
                    selectedFolder,
                    sha256: file.hashes?.SHA256,
                }),
            });

            if (response.ok) {
                const data = await response.json();
                this.activeDownloads[data.downloadId] = {
                    id: data.downloadId,
                    name: model.name,
                    filename: file.name,
                    savePath: data.savePath,
                    modelType: model.type,
                    loadToSlot,
                    targetNode: this.targetNode,
                    buttonElement,
                    sha256: file.hashes?.SHA256,
                };
                this.startDownloadPolling(data.downloadId);
                this.showNotification("⬇ Download Started", file.name, 3000);
                this.showDownloadsPanel();
                this.renderDownloadsPanel();
                if (loadToSlot !== null) this.close();
                return;
            }

            const error = await response.json();
            if (buttonElement) {
                this.resetDownloadButton(buttonElement, "Error!");
                setTimeout(() => this.resetDownloadButton(buttonElement), 2000);
            }
            if (error.error === "duplicate") {
                this.showNotification(
                    "Already Downloaded",
                    `File exists: ${error.existingFile}`,
                    5000,
                );
                if (file.hashes?.SHA256) this.addLocalHash(file.hashes.SHA256);
            } else {
                alert(`Download failed: ${error.error || error.message}`);
            }
        } catch (error) {
            console.error("[CivitAI Browser] Download error:", error);
            if (buttonElement) {
                this.resetDownloadButton(buttonElement, "Error!");
                setTimeout(() => this.resetDownloadButton(buttonElement), 2000);
            }
            alert(`Download error: ${error.message}`);
        }
    };

    proto.getExpectedPath = function(modelType, baseModel, filename) {
        if (modelType === "Checkpoint") {
            return `models/diffusion_models/${filename}`;
        }
        return originalGetExpectedPath.call(this, modelType, baseModel, filename);
    };

    console.log("[Donut CivitAI] PR #25 browser improvements enabled");
}
