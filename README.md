# ComfyUI-DonutCivitaiLocal

A local CivitAI companion extracted from ComfyUI-DonutNodes.

It provides:

- local LoRA SHA256 lookup and CivitAI metadata nodes;
- cached previews, trigger words, duplicate detection, and local library management;
- CivitAI model browsing and download into ComfyUI model folders;
- hash-based LoRA recovery for workflows moved between machines.

## Relationship to CivitAI Nodes

CivitAI's official ComfyUI nodes are the preferred integration for CivitAI cloud generation and its own model-selector workflow. This package remains for local installed-library metadata, preview caching, hash recovery, and the existing `DonutLoRACivitAI*` node IDs.

## Hosted environments

This package writes to shared model folders and may use a CivitAI API key. Enable it only when the service has an explicit per-tenant model-storage, quota, and content-policy design.

## Migration

Install this package alongside old workflows to retain the original `DonutLoRACivitAI*` node IDs. Core DonutNodes no longer owns this CivitAI implementation.
