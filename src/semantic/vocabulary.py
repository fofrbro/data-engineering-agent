"""
Vocabulaire métier (français / anglais) utilisé pour interpréter
les noms de colonnes.

Les mots-clés sont comparés aux mots normalisés du nom de colonne
(minuscules, sans accents). Un mot-clé composé ("unit_price")
doit apparaître comme une suite contiguë de mots.
"""

from src.discovery.schema_profiler import name_tokens


# Rôles sémantiques
IDENTIFIER = "IDENTIFIER"
MEASURE = "MEASURE"
DIMENSION = "DIMENSION"
TEMPORAL = "TEMPORAL"
ATTRIBUTE = "ATTRIBUTE"

# Rôles métier
AMOUNT = "AMOUNT"
PRICE = "PRICE"
QUANTITY = "QUANTITY"
RATIO = "RATIO"
TAX = "TAX"
# Mesure de niveau : elle se moyenne, elle ne s'additionne pas
# (âge, température, note…).
LEVEL = "LEVEL"
CONTACT = "CONTACT"
STATUS = "STATUS"
CATEGORY = "CATEGORY"
GEOGRAPHY = "GEOGRAPHY"
DATE = "DATE"
TIMESTAMP = "TIMESTAMP"
DATE_PART = "DATE_PART"
FLAG = "FLAG"

# Entités métier
CUSTOMER = "CUSTOMER"
PRODUCT = "PRODUCT"
ORDER = "ORDER"
TRANSACTION = "TRANSACTION"


# L'ordre définit la priorité en cas de correspondances multiples :
# "discount_rate" est un RATIO, "unit_price" un PRICE,
# "total_quantity" une QUANTITY, "tax_amount" une TAX (une taxe
# n'est pas le montant des ventes), "average_score" un LEVEL.
MEASURE_KEYWORDS = {
    RATIO: (
        "ratio", "rate", "taux", "pct", "percent", "percentage",
        "pourcentage", "share",
    ),
    PRICE: (
        "price", "prix", "unit_price", "prix_unitaire", "tarif",
    ),
    QUANTITY: (
        "quantity", "qty", "quantite", "qte", "units", "unites",
        "count", "nb", "nombre", "volume",
    ),
    TAX: (
        "tax", "taxe", "taxes", "tva", "vat",
    ),
    LEVEL: (
        "age", "temperature", "temp", "humidity", "humidite", "pressure",
        "pression", "score", "note", "rating", "grade", "level", "niveau",
        "speed", "vitesse", "altitude", "satisfaction", "average", "avg",
        "mean", "moyenne", "moy",
    ),
    AMOUNT: (
        "amount", "montant", "revenue", "revenu", "revenus", "sales",
        "ventes", "ca", "chiffre_affaires", "turnover", "cost", "cout",
        "spend", "depense", "payment", "paiement", "total",
    ),
}

# Coordonnées personnelles : ni mesure ni axe d'analyse.
# "email_address" est un contact, pas une adresse géographique.
CONTACT_KEYWORDS = {
    CONTACT: (
        "email", "mail", "courriel", "phone", "telephone", "tel",
        "mobile", "fax",
    ),
}

DIMENSION_KEYWORDS = {
    GEOGRAPHY: (
        "country", "pays", "city", "ville", "region", "zip", "zipcode",
        "postal", "postcode", "code_postal", "address", "adresse",
        "latitude", "lat", "longitude", "lon", "lng", "departement",
        "province", "continent",
    ),
    STATUS: (
        "status", "statut", "etat",
    ),
    DATE_PART: (
        "year", "annee", "month", "mois", "quarter", "trimestre",
        "week", "semaine", "weekday",
    ),
    CATEGORY: (
        "category", "categorie", "type", "segment", "class", "classe",
        "family", "famille", "channel", "canal", "group", "groupe",
        "brand", "marque",
    ),
}

TEMPORAL_KEYWORDS = {
    TIMESTAMP: (
        "timestamp", "datetime", "at", "time", "heure", "horodatage",
    ),
    DATE: (
        "date", "day", "jour", "dt",
    ),
}

ENTITY_KEYWORDS = {
    CUSTOMER: (
        "customer", "client", "cust", "buyer", "acheteur",
    ),
    PRODUCT: (
        "product", "produit", "item", "article", "sku",
    ),
    ORDER: (
        "order", "commande",
    ),
    TRANSACTION: (
        "transaction", "txn", "invoice", "facture",
    ),
}


def _contains(tokens: list[str], keyword: str) -> bool:
    words = keyword.split("_")
    size = len(words)

    return any(
        tokens[index:index + size] == words
        for index in range(len(tokens) - size + 1)
    )


def match_keyword(
    name: str,
    vocabulary: dict[str, tuple[str, ...]],
) -> tuple[str, str] | None:
    """
    Retourne (rôle, mot-clé) du premier rôle dont un mot-clé
    apparaît dans le nom de colonne, ou None.
    """

    tokens = name_tokens(name)

    for role, keywords in vocabulary.items():
        for keyword in keywords:
            if _contains(tokens, keyword):
                return role, keyword

    return None
