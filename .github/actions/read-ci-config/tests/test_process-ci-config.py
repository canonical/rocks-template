import pytest
import yaml
from pydantic import ValidationError
from src.process_ci_config import CIConfig, ImageEntry
from textwrap import dedent

GENERAL_CI_YAML_WITH_REGISTRIES = """
version: 1
ghcr:
    upload: true
    cve-scan: false
"""

ROCKCRAFT_YAML_MOCK_ROCK_1_0 = """
name: mock-rock
version: 1.0
base: bare
build-base: ubuntu:24.04
"""

ROCKCRAFT_YAML_ANOTHER_ROCK_2_0 = """
name: another-rock
version: 2.0
base: bare
build-base: ubuntu:24.04
"""

ROCKCRAFT_YAML_VERSION_LATEST = """
name: latest-rock
version: latest
base: bare
build-base: ubuntu@24.04
"""

ROCKCRAFT_YAML_INVALID_BASE = """
name: invalid-rock
version: 1.0
base: ubuntu:noble
"""

ROCKCRAFT_YAML_DEVEL_BASE = """
name: devel-rock
version: 1.0
base: bare
build-base: devel
"""


# mock the open function to return the content of ROCKCRAFT_YAML_MOCK_ROCK_1_0 or ROCKCRAFT_YAML_ANOTHER_ROCK_2_0
@pytest.fixture
def fake_open(monkeypatch):
    from io import StringIO

    def fake_file_open(file, mode="r", encoding=None):
        if "mock-rock/1.0/rockcraft.yaml" in file:
            return StringIO(ROCKCRAFT_YAML_MOCK_ROCK_1_0)
        elif "another-rock/2.0/rockcraft.yaml" in file:
            return StringIO(ROCKCRAFT_YAML_ANOTHER_ROCK_2_0)
        elif "latest-rock/latest/rockcraft.yaml" in file:
            return StringIO(ROCKCRAFT_YAML_VERSION_LATEST)
        elif "invalid-rock/1.0/rockcraft.yaml" in file:
            return StringIO(ROCKCRAFT_YAML_INVALID_BASE)
        elif "devel-rock/1.0/rockcraft.yaml" in file:
            return StringIO(ROCKCRAFT_YAML_DEVEL_BASE)
        else:
            raise FileNotFoundError(f"No such file: {file}")

    monkeypatch.setattr("builtins.open", fake_file_open)


def test_image_name_and_tag_pass(fake_open):
    name, tag = CIConfig.image_name_and_tag("mock-rock/1.0")
    assert name == "mock-rock"
    assert tag == "1.0-24.04_edge"
    name, tag = CIConfig.image_name_and_tag("another-rock/2.0")
    assert name == "another-rock"
    assert tag == "2.0-24.04_edge"


def test_image_name_and_tag_with_latest_version_pass(fake_open, capsys):
    name, tag = CIConfig.image_name_and_tag("latest-rock/latest")
    assert name == "latest-rock"
    assert tag == "latest-24.04_edge"
    captured = capsys.readouterr()
    assert (
        captured.out.rstrip("\n")
        == "::warning file=$file::Using 'latest' as version — tag set to 'latest'"
    )


def test_image_name_and_tag_with_invalid_base_should_fail(fake_open):
    with pytest.raises(
        ValueError,
        match="Base 'ubuntu:noble' in 'invalid-rock/1.0/rockcraft.yaml' does not match the expected pattern.",
    ):
        _ = CIConfig.image_name_and_tag("invalid-rock/1.0")


def test_image_name_and_tag_with_devel_base_pass(fake_open):
    name, tag = CIConfig.image_name_and_tag("devel-rock/1.0")
    assert name == "devel-rock"
    assert tag == "1.0-devel_edge"


def test_image_base_with_at_symbol_should_pass(fake_open):
    name, tag = CIConfig.image_name_and_tag("latest-rock/latest")
    assert name == "latest-rock"
    assert tag == "latest-24.04_edge"


def test_image_with_other_wildcard_should_fail():
    sample_yaml = GENERAL_CI_YAML_WITH_REGISTRIES + dedent(
        """\
        images:
            - directory: "*/rockcraft.yaml"
        """
    )
    config_data = yaml.safe_load(sample_yaml)
    with pytest.raises(
        ValueError,
        match="Wildcard '\\*' must be the only character in directory",
    ):
        _ = CIConfig(**config_data)


def test_pydantic_model_loads_configuration():
    sample_yaml = GENERAL_CI_YAML_WITH_REGISTRIES + dedent(
        """\
        images:
            - directory: mock-rock/1.0
        """
    )
    config_data = yaml.safe_load(sample_yaml)
    ci_config = CIConfig(**config_data)
    assert ci_config.ghcr.upload is True  # pylint: disable=no-member
    assert (
        ci_config.ghcr.cve_scan is False  # pylint: disable=no-member
    )  # pylint: disable=no-member
    assert ci_config.model_dump() == {
        "version": 1,
        "ghcr": {"upload": True, "cve_scan": False},
        "images": [{"directory": "mock-rock/1.0"}],
    }


def test_cve_scan_true_with_upload_false_should_fail():
    sample_yaml = dedent(
        """\
        version: 1
        ghcr:
            upload: false
            cve-scan: true
        images:
        """
    )
    config_data = yaml.safe_load(sample_yaml)
    with pytest.raises(ValidationError) as exc_info:
        _ = CIConfig(**config_data)
    assert "cve-scan can not be true if upload is false" in str(exc_info.value)


def test_empty_images_should_pass():
    sample_yaml = GENERAL_CI_YAML_WITH_REGISTRIES + "\nimages:\n"
    config_data = yaml.safe_load(sample_yaml)
    ci_config = CIConfig(**config_data)
    assert ci_config.images == []
    build_matrix = ci_config.build_matrix()
    assert build_matrix == {"include": []}


def test_valid_simple_configuration_should_pass(fake_open):
    sample_yaml = GENERAL_CI_YAML_WITH_REGISTRIES + dedent(
        """\
        images:
            - directory: mock-rock/1.0
        """
    )
    config_data = yaml.safe_load(sample_yaml)
    ci_config = CIConfig(**config_data)
    build_matrix = ci_config.build_matrix()
    expected_build_matrix = {
        "include": [
            {
                "name": "mock-rock",
                "tag": "1.0-24.04_edge",
                "directory": "mock-rock/1.0",
                "artifact-name": "mock-rock-1.0",
            },
        ]
    }
    assert build_matrix == expected_build_matrix


def test_image_without_registries_should_pass(fake_open):
    sample_yaml = dedent(
        """\
        version: 1
        ghcr:
            upload: true
            cve-scan: false
        images:
            - directory: mock-rock/1.0
        """
    )
    config_data = yaml.safe_load(sample_yaml)
    ci_config = CIConfig(**config_data)
    build_matrix = ci_config.build_matrix()
    expected_build_matrix = {
        "include": [
            {
                "name": "mock-rock",
                "tag": "1.0-24.04_edge",
                "directory": "mock-rock/1.0",
                "artifact-name": "mock-rock-1.0",
            }
        ]
    }
    assert build_matrix == expected_build_matrix


def test_duplicated_image_directory_should_deduplicate(fake_open):
    sample_yaml = dedent(
        """\
        version: 1
        ghcr:
            upload: true
            cve-scan: false
        images:
            - directory: mock-rock/1.0
            - directory: mock-rock/1.0
        """
    )
    config_data = yaml.safe_load(sample_yaml)
    ci_config = CIConfig(**config_data)
    build_matrix = ci_config.build_matrix()
    expected_build_matrix = {
        "include": [
            {
                "name": "mock-rock",
                "tag": "1.0-24.04_edge",
                "directory": "mock-rock/1.0",
                "artifact-name": "mock-rock-1.0",
            }
        ]
    }
    assert build_matrix == expected_build_matrix


@pytest.fixture
def fake_glob(monkeypatch):
    def fake_glob(pattern, recursive=True):
        return ["mock-rock/1.0/rockcraft.yaml", "another-rock/2.0/rockcraft.yaml"]

    monkeypatch.setattr("glob.glob", fake_glob)


def test_images_wildcard_should_glob_rockcraft_yaml(fake_glob, fake_open):
    sample_yaml = dedent(
        """\
        version: 1
        ghcr:
            upload: true
            cve-scan: false
        images:
            - directory: "*"
        """
    )
    config_data = yaml.safe_load(sample_yaml)
    ci_config = CIConfig(**config_data)
    assert ci_config.images == [
        ImageEntry(directory="mock-rock/1.0"),
        ImageEntry(directory="another-rock/2.0"),
    ]
    build_matrix = ci_config.build_matrix()
    expected_matrix = {
        "include": [
            {
                "name": "mock-rock",
                "tag": "1.0-24.04_edge",
                "directory": "mock-rock/1.0",
                "artifact-name": "mock-rock-1.0",
            },
            {
                "name": "another-rock",
                "tag": "2.0-24.04_edge",
                "directory": "another-rock/2.0",
                "artifact-name": "another-rock-2.0",
            },
        ]
    }
    assert build_matrix == expected_matrix


def test_multiple_images_wildcard_should_glob_rockcraft_yaml(fake_glob, fake_open):
    sample_yaml = GENERAL_CI_YAML_WITH_REGISTRIES + dedent(
        """\
        images:
            - directory: "mock-rock/1.0"
            - directory: "another-rock/2.0"
            - directory: "*"
        """
    )
    config_data = yaml.safe_load(sample_yaml)
    ci_config = CIConfig(**config_data)
    build_matrix = ci_config.build_matrix()
    expected_build_matrix = {
        "include": [
            {
                "name": "mock-rock",
                "tag": "1.0-24.04_edge",
                "directory": "mock-rock/1.0",
                "artifact-name": "mock-rock-1.0",
            },
            {
                "name": "another-rock",
                "tag": "2.0-24.04_edge",
                "directory": "another-rock/2.0",
                "artifact-name": "another-rock-2.0",
            },
        ]
    }
    assert build_matrix == expected_build_matrix


def test_yaml_missing_images_should_fail():
    sample_yaml = GENERAL_CI_YAML_WITH_REGISTRIES
    config_data = yaml.safe_load(sample_yaml)
    with pytest.raises(ValidationError):
        _ = CIConfig(**config_data)


def test_yaml_missing_ghcr_should_fail():
    sample_yaml = dedent(
        """\
        images:
            - directory: mock-rock/1.0
        """
    )
    config_data = yaml.safe_load(sample_yaml)
    with pytest.raises(ValidationError):
        _ = CIConfig(**config_data)
