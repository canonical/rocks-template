# Rocks template repo

This repository template provides a basic setup to help you get started quickly with developing your own rock.

## Table of Contents

- [Setup Instructions](#setup-instructions)
- [Directory Structure](#directory-structure)
- [Building the Rock](#building-the-rock)

## Setup Instructions

### 1. Start a new repository from this template

Check GitHub's documentation on [creating a repository from a template](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-repository-from-a-template)

#### 1.1. Create secrets, if needed

> [!IMPORTANT]
> If your repository is **internal** or **private**, you need to create the
> following secrets in your repository:
>
> - `REPO_CLONER_TOKEN`: use a [fine grained token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-fine-grained-personal-access-token) with `read:content` and
> `read:metadata` permissions. **Make sure the token's "resource owner" is _canonical_**, and has access to the right repositories (not just public in this case).
> Also, please note that fine-grained tokens have an expiration date. So if and when experiencing CI problems checking out the repository, make sure the token is still valid.

### 2. Customize the Template

This template comes with a basic setup to get you started. Here's what you need to customize:

- **`rockcraft.yaml`**: This is your rock's [recipe](https://documentation.ubuntu.com/rockcraft/en/stable/reference/rockcraft.yaml/)! Adjust its contents, as well as its parent directories' names according to your rock's name and version.
- **`task.yaml`**: This is your tests' file, it contains the required instructions written in bash for your rock to be tested using [spread](https://github.com/canonical/spread).
- **`SECURITY.md.template`**: Edit the template with your repo's details and set the security policy by renaming this file to `SECURITY.md`.
- **`CODEOWNERS`**: Optional, but recommended. Read more about [CODEOWNERS](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners).

## Directory Structure

Here's an overview of the directory structure of the repository:

```
.github/
   |─ ...
   └─ ci.yaml                 # CI configuration file


my-rock-name/                 # Directory containing all versions of a single rock
   └─ 0.1/                    # Directory containing the rock project file for a specific version
      |─ rockcraft.yaml       # Rock project file
      |─ spread.yaml          # Spread test configuration
      └─ spread/              # Spread tests directory
         |─ .extension        # Functions used internally by spread tests
         └─ general/test/     # Directory containing tests
            └─ task.yaml      # Test file
.gitignore
CODEOWNERS                    
README.md                     # Top level document containing this specification
SECURITY.md.template          # Security policy template
```

## Building, testing and uploading the Rock

To build, test and upload the rock to GHCR, simply commit your `rockcraft.yaml`
file and check the GitHub actions.

> [!NOTE]
> Before committing your `rockcraft.yaml`, it is recommended that you `pack` it
> with [Rockcraft](https://snapcraft.io/rockcraft) run a smoke test locally.
> Check the [Rockcraft documentation](https://documentation.ubuntu.com/rockcraft) to learn more.

## Sync with template

A `Makefile` is provided to sync the repository with the latest template changes. To do so, simply run:

```bash
make sync-with-template
```

## Override the behavior of the CI

The behavior of the CI is configured in `.github/ci.yaml`, which defines the following parameters:

| Property | Required | Type | Description |
|---|---|---|---|
| ghcr | True | Dict[str, bool] | The configuration regarding the GHCR. |
| ghcr.upload | True | bool | Whether the images should be uploaded to GHCR after successful build and test. |
| ghcr.cve-scan | True | bool | Whether the continuous vulnerability scanning cron workflow should be run. When set to `true`, `ghcr.upload` should also be `true`. |
| registries | True | Dict[str, Any] | The configuration regarding the additional registries. |
| registries.\<name\> | False | Dict[str, Any] | The name of the registry. |
| registries.\<name\>.uri | True | str | The URL of the registry. |
| registries.\<name\>.auth | True | conlist[Any, min_items=1, max_items=1] | The authentication configurations to access the registry. Currently only one single configuration is supported. |
| registries.\<name\>.auth[0].method | True | str | The method of the authentication configuration. Supported methods are `basic`, `bearer`, `ecr` and `ecr-public`. |
| registries.\<name\>.auth[0].config | True | Dict[str, str] | The configuration of the corresponding authentication method. See [below](#registry-authentication-configuration) for details. |
| images | True | List[Any] | The list of images to be built, tested and uploaded. |
| images.*.directory | True | str | The directory to the `rockcraft.yaml` file. A quoted asterisk symbol `'*'` matches all the directories that contain a `rockcraft.yaml` file within this repo. |
| images.*.registries | True | Optional[List[str]] | The list of additional registries (defined in `registries`) to which the image should be published. |


### Registry authentication configuration

The following table lists the supported authentication methods and their
corresponding configuration parameters.

The configuration arguments are the string literals of the secret names stored
in the repository's secrets, prepended with the prefix `secrets.`. E.g., for the
`bearer` method, if the `token` secret stored in the repository is named
`MY_BEARER_TOKEN`, then the configuration should be `token:
secrets.MY_BEARER_TOKEN`.


| Method | Configuration Parameters | Description |
|---|---|---|
| basic | username: str<br>password: str | Basic authentication using a username and password. |
| bearer | token: str | Bearer token authentication. |
| ecr<br>ecr-public | region: str<br>username: str<br>password: str | AWS ECR (public) authentication for private ECR registries.<br>Use `username` for AWS access key ID and `password` for AWS secret access key. |


### Example Configuration
Here is an example configuration that builds all the images within the
repository, uploads them to GHCR and an additional private registry with basic
authentication, and enables the CVE scan cron workflow:

```yaml
ghcr:
  upload: true
  cve-scan: true
registries:
  my-private-registry:
    uri: my.private.registry.com
    auth:
      - method: basic
        config:
          username: secrets.MY_PRIVATE_REGISTRY_USERNAME
          password: secrets.MY_PRIVATE_REGISTRY_PASSWORD
images:
   - directory: '*'
     registries:
      - my-private-registry
