import os
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from shared import pr25_civitai_port as port


class PR25CivitAIPortTests(unittest.TestCase):
    def test_selected_folder_stays_inside_model_root(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.object(port, "get_model_root", return_value=root):
                path = port.get_selected_download_path(
                    "LORA",
                    "SDXL 1.0",
                    "model.safetensors",
                    selected_folder="artists/person",
                )

                self.assertEqual(
                    path,
                    os.path.join(root, "artists", "person", "model.safetensors"),
                )
                self.assertTrue(os.path.isdir(os.path.join(root, "artists", "person")))

                with self.assertRaises(ValueError):
                    port.get_selected_download_path(
                        "LORA",
                        "SDXL 1.0",
                        "model.safetensors",
                        selected_folder="../../outside",
                    )

                with self.assertRaises(ValueError):
                    port.get_selected_download_path(
                        "LORA",
                        "SDXL 1.0",
                        "../model.safetensors",
                        selected_folder="",
                    )

    def test_none_folder_preserves_automatic_lora_subfolder(self):
        with tempfile.TemporaryDirectory() as root:
            with (
                patch.object(port, "get_model_root", return_value=root),
                patch.object(
                    port.civitai_download,
                    "normalize_base_model",
                    return_value="sdxl",
                ),
            ):
                path = port.get_selected_download_path(
                    "LORA",
                    "SDXL 1.0",
                    "style.safetensors",
                    selected_folder=None,
                )

        self.assertEqual(path, os.path.join(root, "sdxl", "style.safetensors"))

    def test_checkpoint_root_uses_physical_diffusion_models_directory(self):
        fake_folder_paths = types.SimpleNamespace(models_dir="/comfy/models")
        with (
            patch.object(port, "HAS_FOLDER_PATHS", True),
            patch.object(port, "folder_paths", fake_folder_paths),
        ):
            self.assertEqual(
                port.get_model_root("Checkpoint"),
                os.path.abspath("/comfy/models/diffusion_models"),
            )

    def test_folder_listing_includes_root_and_existing_subfolders(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "one", "two"))
            with (
                patch.object(port, "get_model_root", return_value=root),
                patch.object(
                    port.civitai_download,
                    "normalize_base_model",
                    return_value="sdxl",
                ),
            ):
                data = port.list_download_folders("LORA", "SDXL 1.0")

        values = {entry["value"] for entry in data["folders"]}
        self.assertIn("", values)
        self.assertIn("one", values)
        self.assertIn("one/two", values)
        self.assertIn("sdxl", values)
        self.assertEqual(data["defaultFolder"], "sdxl")

    def test_aria2_missing_falls_back_to_current_downloader(self):
        fallback = Mock(return_value="fallback-result")
        fake_self = object()
        with (
            patch.object(port.shutil, "which", return_value=None),
            patch.object(port, "_ORIGINAL_DOWNLOAD_THREAD", fallback),
        ):
            result = port._aria2_download_thread(
                fake_self,
                "id",
                "https://civitai.com/api/download/models/1",
                "/tmp/model.safetensors",
                None,
                None,
                "Checkpoint",
                None,
            )

        self.assertEqual(result, "fallback-result")
        fallback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
