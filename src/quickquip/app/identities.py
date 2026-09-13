"""Application identity sources: Bot and Web retain independent file caches."""
from quickquip.common.identity_sources import IdentityRepository, IdentitySnapshot, identities

web_identities = IdentityRepository()

__all__ = ["IdentityRepository", "IdentitySnapshot", "identities", "web_identities"]
