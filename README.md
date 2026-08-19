# GuidelineOps-CN

GuidelineOps-CN is a small foundation for evidence-oriented guideline
operations in research and education. This initial release provides the
package and command-line entry point only; adapters and other data workflows
are not included yet.

The project is for research and educational use. It is not a medical device,
does not provide medical advice, and must not be used to make or support
clinical decisions. Consult qualified professionals and the original sources
for any real-world health question.

## Install and run

Python 3.11 or newer and [uv](https://docs.astral.sh/uv/) are required:

```bash
uv sync
uv run guidelineops --help
```

The command currently exposes the project help text. Future functionality
will be documented when it is implemented.
