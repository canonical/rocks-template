import argparse
import glob
import json
import os
import re
from collections import defaultdict
from enum import Enum
from typing import Optional, Type, Union

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


class BaseAuthConfig(BaseModel):
    @pydantic.model_serializer
    def add_prefix(self):
        return {f"registry-auth-{k}": v for k, v in dict(self).items()}


class BasicAuth(BaseAuthConfig):
    username: str = Field(
        ...,
        description="The name of the GitHub Action secret of the username for basic authentication",
    )
    password: str = Field(
        ...,
        description="The name of the GitHub Action secret of the password for basic authentication",
    )

    @pydantic.field_validator("username", "password")
    def _ensure_secret_format(cls, v):  # pylint: disable=no-self-argument
        if not v or not isinstance(v, str):
            raise ValueError("Credential name must be a non-empty string.")
        if not v.startswith("secrets."):
            raise ValueError("Credential name must start with 'secrets.'")
        return v.removeprefix("secrets.")


class ECRAuth(BasicAuth):
    region: str = Field(..., description="The AWS region for ECR authentication")

    @pydantic.model_serializer
    def add_prefix(self):
        r = super().add_prefix()
        r["registry-auth-method"] = "ecr"
        return r


class ECRPublicAuth(ECRAuth):
    @pydantic.model_serializer
    def add_prefix(self):
        r = super().add_prefix()
        r["registry-auth-method"] = "ecr-public"
        return r


class BearerAuth(BaseAuthConfig):
    token: str = Field(
        ...,
        description="The name of the GitHub Action secret of the token for bearer authentication",
    )

    @pydantic.field_validator("token")
    def _ensure_secret_format(cls, v):  # pylint: disable=no-self-argument
        if not v or not isinstance(v, str):
            raise ValueError("Credential name must be a non-empty string.")
        if not v.startswith("secrets."):
            raise ValueError("Credential name must start with 'secrets.'")
        return v.removeprefix("secrets.")


class AuthType(str, Enum):
    BASIC = "basic"
    BEARER = "bearer"
    ECR = "ecr"
    ECR_PUBLIC = "ecr-public"


AUTH_MODELS: dict[AuthType, Type[BaseModel]] = {
    AuthType.BASIC: BasicAuth,
    AuthType.BEARER: BearerAuth,
    AuthType.ECR: ECRAuth,
    AuthType.ECR_PUBLIC: ECRPublicAuth,
}


class RegistrySecretEntry(BaseModel):
    # Field `auth` is an enumerate of different authentication methods
    method: str = Field(
        ..., description="The type of authentication method", alias="method"
    )
    config: Union[BasicAuth, BearerAuth, ECRAuth] = Field(
        ..., description="The authentication method for the registry"
    )

    model_config = pydantic.ConfigDict(extra="forbid")

    @pydantic.model_serializer
    def add_prefix(self):
        r = {"registry-auth-method": self.method}
        r.update(self.config.model_dump())  # pylint: disable=no-member
        return r

    @pydantic.field_validator("method", mode="before")
    def _ensure_method_known(cls, v):  # pylint: disable=no-self-argument
        if isinstance(v, str):
            try:
                return AuthType(v)
            except ValueError as e:
                raise ValueError(
                    f"Invalid auth method '{v}'. Supported methods are: {', '.join([m.value for m in AuthType])}."
                ) from e
        return v

    @pydantic.field_validator("config", mode="before")
    def _ensure_config_type(cls, v, info):  # pylint: disable=no-self-argument
        if v is None:
            raise ValueError("Auth config must be provided.")
        if isinstance(v, BaseAuthConfig):
            return v
        if not isinstance(v, dict):
            raise ValueError("Auth config must be a dictionary.")
        method = info.data.get("method")
        model_cls = AUTH_MODELS.get(method)
        if model_cls is None:
            raise ValueError(
                f"Unsupported auth method '{method}'. Supported methods are: {', '.join([m.value for m in AuthType])}."
            )
        return model_cls(**v)


class RegistryConfigEntry(BaseModel):
    uri: str = Field(..., description="The URL of the registry")
    auth: RegistrySecretEntry = Field(
        ...,
        description="The GitHub Action secrets for authentication",
    )

    model_config = pydantic.ConfigDict(extra="forbid")

    @pydantic.field_validator("auth", mode="before")
    def _unpack_auth_list(cls, v):  # pylint: disable=no-self-argument
        if not isinstance(v, (list)):
            raise ValueError("Auth must be provided as a list.")
        if len(v) != 1:
            raise ValueError("Auth list must contain exactly one entry.")
        return v[0]


class ImageEntry(BaseModel):
    directory: str = Field(
        ..., description="Path to the directory containing the rockcraft.yaml"
    )
    registries: Optional[list[str]] = Field(
        description="List of registry names that match the registry config",
        default_factory=list,
    )
    # TODO: Add support for building pro-enabled rocks

    model_config = pydantic.ConfigDict(extra="forbid")


class CIConfig(BaseModel):
    version: int = Field(..., description="Version of the CI configuration")
    ghcr: GHCRConfig = Field(
        ..., description="Configuration for GitHub Container Registry"
    )
    # We need to construct registries before images to validate the references of "registries" in images
    registries: dict[str, RegistryConfigEntry] = Field(
        description="Mapping of registry names to their configurations"
    )
    images: list[ImageEntry] = Field(description="List of images to be processed")

    model_config = pydantic.ConfigDict(extra="forbid")

    @pydantic.field_validator("version")
    def _ensure_version_supported(cls, v):  # pylint: disable=no-self-argument
        if v != 1:
            raise ValueError("Only version 1 of the CI configuration is supported.")
        return v

    @pydantic.field_validator("registries", "images", mode="before")
    def _ensure_registries_dict(cls, v):  # pylint: disable=no-self-argument
        if v is None:
            return {}
        return v

    @pydantic.field_validator("images", mode="before")
    def _ensure_images_list(cls, v):  # pylint: disable=no-self-argument
        if v is None:
            return []
        return v

    @pydantic.field_validator("images", mode="after")
    def _ensure_image_resitries_exist(cls, v, info):  # pylint: disable=no-self-argument
        if not v:
            return []
        registry_keys = info.data.get("registries", {}).keys()
        for image in v:
            for registry in image.registries:
                if registry not in registry_keys:
                    raise ValueError(
                        f"Registry '{registry}' in image '{image.directory}' is not defined in registries."
                    )
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
                    expanded_images.append(
                        ImageEntry(
                            directory=os.path.dirname(d), registries=image.registries
                        )
                    )
            else:
                expanded_images.append(image)
        return expanded_images

    @staticmethod
    def artifact_name(dir: str) -> str:
        return dir.replace("/", "-")

    @staticmethod
    def image_name_and_tag(image_directory: str) -> tuple[str, str]:
        base_version_id_pattern = r"(\d{2}\.\d{2})"
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
                    f"Base '{base}' in '{image_directory}/rockcraft.yaml' does not match the expected pattern."
                )
            base = match.group(1)
            if version == "latest":
                print(
                    "::warning file=$file::Using 'latest' as version — tag set to 'latest'"
                )
            tag = f"{version}-{base}_{channel}"
        return name, tag

    def build_matrix(self) -> dict:
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

    def upload_matrix(self):
        matrix = {"include": []}
        image_registries = defaultdict(set)
        for image in self.images:  # pylint: disable=not-an-iterable
            image_registries[image.directory].update(set(image.registries))
        for image_directory, registries in image_registries.items():
            if not registries:
                continue
            name, tag = self.image_name_and_tag(image_directory)
            for r in sorted(list(registries)):
                registry = self.registries[r]  # pylint: disable=unsubscriptable-object
                matrix["include"].append(
                    {
                        "name": name,
                        "tag": tag,
                        "artifact-name": self.artifact_name(image_directory),
                        "registry-uri": registry.uri,
                        **registry.auth.model_dump(
                            by_alias=True
                        ),  # pylint: disable=no-member
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
        gh_out.write(
            f"upload-matrix={json.dumps(ci_config.upload_matrix(), indent=indent)}\n"
        )


if __name__ == "__main__":
    main()
