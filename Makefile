.PHONY: release-patch release-minor release-major

release-patch:
	TAG=true scripts/bump_version.sh patch

release-minor:
	TAG=true scripts/bump_version.sh minor

release-major:
	TAG=true scripts/bump_version.sh major
