from pathlib import Path
import subprocess
import sys
from typing import Optional


class CombinedPipeline:
    """Single class exposing two pipeline methods: pipeline and pipeline_2.

    Each method invokes the corresponding script with a subprocess, passing the
    PDF path and output tag. This keeps the original scripts intact while
    providing a single importable class with two strategy methods.
    """

    def __init__(self, logger=None):
        self.logger = logger
        # Try to import run_pipeline functions if available
        self._pipeline_fn = None
        self._pipeline2_fn = None
        # Prefer absolute import (works when running from repo root). Fall back to package-relative if needed.
        try:
            import importlib
            pmod = importlib.import_module('pipeline')
            self._pipeline_fn = getattr(pmod, 'run_pipeline', None)
        except Exception:
            try:
                from .. import pipeline as pmod
                self._pipeline_fn = getattr(pmod, 'run_pipeline', None)
            except Exception:
                self._pipeline_fn = None
        try:
            import importlib
            p2mod = importlib.import_module('pipeline_2')
            self._pipeline2_fn = getattr(p2mod, 'run_pipeline', None)
        except Exception:
            try:
                from .. import pipeline_2 as p2mod
                self._pipeline2_fn = getattr(p2mod, 'run_pipeline', None)
            except Exception:
                self._pipeline2_fn = None

    def pipeline(self, pdf_path: Path, out_root: Path, output_tag: Optional[str] = None, **opts) -> Path:
        """Run pipeline.py; prefer in-process call to run_pipeline(), fallback to subprocess."""
        if self._pipeline_fn:
            # call in-process
            self._pipeline_fn(pdf_path, output_tag or 'pipeline_output', project_root=out_root, **opts)
            return out_root
        # fallback to subprocess
        cmd = [sys.executable, str(Path('pipeline.py').resolve()), '--project-root', str(out_root.resolve())]
        if pdf_path:
            cmd += ['--pdf', str(pdf_path)]
        if output_tag:
            cmd += ['--output-tag', str(output_tag)]
        subprocess.run(cmd, check=True)
        return out_root

    def pipeline_2(self, pdf_path: Path, out_root: Path, output_tag: Optional[str] = None, **opts) -> Path:
        """Run pipeline_2.py; prefer in-process call to run_pipeline(), fallback to subprocess."""
        if self._pipeline2_fn:
            self._pipeline2_fn(pdf_path, output_tag or 'pipeline2_output', project_root=out_root, **opts)
            return out_root
        cmd = [sys.executable, str(Path('pipeline_2.py').resolve()), '--project-root', str(out_root.resolve())]
        if pdf_path:
            cmd += ['--pdf', str(pdf_path)]
        if output_tag:
            cmd += ['--output-tag', str(output_tag)]
        subprocess.run(cmd, check=True)
        return out_root
