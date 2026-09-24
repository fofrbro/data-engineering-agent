class DiscoveryError(Exception):
    """Erreur de base de la couche de découverte."""


class EmptyFileError(DiscoveryError):
    """Le fichier existe mais ne contient aucun octet."""


class UnsupportedFormatError(DiscoveryError):
    """Le format du fichier n'est pas pris en charge."""


class UnreadableFileError(DiscoveryError):
    """Le fichier a un format connu mais ne peut pas être lu."""
