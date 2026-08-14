import re
from pathlib import Path


def test_ghcr_workflow_publishes_a_pinned_multi_arch_image_from_integration_only():
    workflow = Path(".github/workflows/publish-image.yml").read_text(encoding="utf-8")

    for required in (
        "branches: [integration]",
        "workflow_dispatch: {}",
        "contents: read",
        "packages: write",
        "registry: ghcr.io",
        "images: ghcr.io/${{ github.repository }}",
        "platforms: linux/amd64,linux/arm64",
        "push: true",
        "secrets.GITHUB_TOKEN",
    ):
        assert required in workflow

    assert "pull_request" not in workflow
    assert set(re.findall(r"uses:\s*([^\s#]+)", workflow))
    for action in re.findall(r"uses:\s*([^\s#]+)", workflow):
        assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", action), action


def test_readme_documents_the_arm64_ghcr_pull_without_embedding_credentials():
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "ghcr.io/0xstillb/bitget-tracker:integration" in readme
    assert "linux/arm64" in readme
    assert "read:packages" in readme
    assert "docker login ghcr.io" in readme
    assert "do not publish" in readme.lower()
