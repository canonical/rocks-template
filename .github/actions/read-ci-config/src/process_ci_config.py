import argparse
import glob
import json
import os
import re

import pydantic
import yaml
from pydantic import BaseModel, Field


class GHCRConfig(BaseModel):
    upload: bool = Field(..., description="Flag to indicate if upload is enabled")
    cve_scan: bool = Field(
        ...,
        description="Flag to enable continuous security scanning",
        alias="cve-scan",
    )

    model_config = pydantic.ConfigDict(extra="forbid")

    @pydantic.field_validator("cve_scan")
    def _ensure_cve_scan(cls, v, info):  # pylint: disable=no-self-argument
        if v and not info.data.get("upload", False):
            raise ValueError("cve-scan can not be true if upload is false")
        return v


class ImageEntry(BaseModel):
    directory: str = Field(
        ..., description="Path to the directory containing the rockcraft.yaml"
    )

    model_config = pydantic.ConfigDict(extra="forbid")


class CIConfig(BaseModel):
    version: int = Field(..., description="Version of the CI configuration")
    ghcr: GHCRConfig = Field(
        ..., description="Configuration for GitHub Container Registry"
    )
    images: list[ImageEntry] = Field(description="List of images to be processed")

    model_config = pydantic.ConfigDict(extra="forbid")

    @pydantic.field_validator("version")
    def _ensure_version_supported(cls, v):  # pylint: disable=no-self-argument
        if v != 1:
            raise ValueError("Only version 1 of the CI configuration is supported.")
        return v

    @pydantic.field_validator("images", mode="before")
    def _ensure_images_list(cls, v):  # pylint: disable=no-self-argument
        if v is None:
            return []
        return v

    @pydantic.field_validator("images", mode="after")
    def _expand_image_directories(cls, v):  # pylint: disable=no-self-argument
        if not v:
            return v
        expanded_images = []
        for image in v:
            if "*" in image.directory:
                if image.directory != "*":
                    raise ValueError(
                        "Wildcard '*' must be the only character in directory"
                    )
                # Expand the wildcard using glob
                dirs = glob.glob("**/rockcraft.yaml", recursive=True)
                for d in dirs:
                    expanded_images.append(ImageEntry(directory=os.path.dirname(d)))
            else:
                expanded_images.append(image)
        return expanded_images

    @staticmethod
    def artifact_name(dir: str) -> str:
        return dir.replace("/", "-")

    @staticmethod
    def image_name_and_tag(image_directory: str) -> tuple[str, str]:
        """Read the rockcraft.yaml in the given directory to get the image name and tag.

        Args:
            image_directory (str)

        Raises:
            ValueError

        Returns:
            tuple[str, str]: (name, tag)
        """
        # Pattern to match base version id like '22.04', '20.04', or 'devel'
        base_version_id_pattern = r"(\d{2}(\.|@)\d{2}|devel)$"
        with open(
            os.path.join(image_directory, "rockcraft.yaml"), "r", encoding="utf-8"
        ) as f:
            rockcraft = yaml.safe_load(f)
            name = rockcraft["name"]
            version = rockcraft["version"]
            channel = "edge"
            base = rockcraft["base"]
            if base == "bare":
                base = rockcraft["build-base"]
            match = re.search(base_version_id_pattern, base)
            if not match:
                raise ValueError(
                    f"Base '{base}' in '{image_directory}/rockcraft.yaml' does not match the expected pattern.\n"
                    + f"See https://documentation.ubuntu.com/rockcraft/stable/reference/rockcraft.yaml/#base for supported base values."
                )
            base = match.group(1)
            if version == "latest":
                print(
                    "::warning file=$file::Using 'latest' as version — tag set to 'latest'"
                )
            tag = f"{version}-{base}_{channel}"
        return name, tag

    def build_matrix(self) -> dict:
        """Generate the build matrix for GitHub Actions.

        Returns:
            dict: Build matrix
        """
        matrix = {"include": []}
        added_image_dirs = set()
        for image in self.images:  # pylint: disable=not-an-iterable
            if image.directory in added_image_dirs:
                continue
            added_image_dirs.add(image.directory)
            name, tag = self.image_name_and_tag(image.directory)
            matrix["include"].append(
                {
                    "name": name,
                    "tag": tag,
                    "directory": image.directory,
                    "artifact-name": self.artifact_name(image.directory),
                }
            )
        return matrix

    def ghcr_config_json(self, **kwargs):
        return json.dumps(
            self.ghcr.model_dump(by_alias=True), **kwargs  # pylint: disable=no-member
        )


def main():
    parser = argparse.ArgumentParser(
        description="Process and validate CI configuration."
    )
    parser.add_argument(
        "config_path", type=str, help="Path to the CI configuration YAML"
    )
    args = parser.parse_args()

    with open(args.config_path, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f)

    ci_config = CIConfig(**config_data)

    # Writes to GitHub outputs
    with open(
        os.environ.get("GITHUB_OUTPUT", "/dev/stdout"), "a", encoding="utf-8"
    ) as gh_out:
        print("Exporting config to", gh_out.name)
        indent = 2 if gh_out.name == "/dev/stdout" else None
        gh_out.write(
            f"ghcr-upload={json.dumps(ci_config.ghcr.upload, indent=indent)}\n"  # pylint: disable=no-member
        )
        gh_out.write(
            f"ghcr-cve-scan={json.dumps(ci_config.ghcr.upload, indent=indent)}\n"  # pylint: disable=no-member
        )
        gh_out.write(
            f"build-matrix={json.dumps(ci_config.build_matrix(), indent=indent)}\n"
        )


if __name__ == "__main__":
    main()
