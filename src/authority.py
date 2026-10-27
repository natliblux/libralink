from collections.abc import Callable
from normalization.default import normalize

class Authority:

    def __init__(
        self,
        authority_id: str,
        entry_index: int,
        years: str,
        aut_type: str,
        ind1: str,
        ind2: str,
        preferred_a: str,
        preferred_b: list[str],
        variant_a: str,
        variant_b: list[str],
        n_variants: int,
        normalizer: Callable[[str], str] = normalize
    ) -> None:

        self.normalizer = normalizer
        self.authority_id = authority_id.strip()
        self.entry_index = entry_index
        self.id = f"{self.authority_id}-{self.entry_index:03d}"
        self.years = self._clean(years)
        self.aut_type = aut_type
        self.ind1 = self._clean(ind1)
        self.ind2 = self._clean(ind2)
        self.n_variants = n_variants

        # preferred version
        self.preferred_a = self._clean(preferred_a)
        self.preferred_a_norm = self.normalizer(self.preferred_a) if self.preferred_a else None
        self.preferred_b = self._clean_list(preferred_b)
        self.preferred_b_norm = [self.normalizer(b) for b in self.preferred_b]
        self.preferred = f"{self.preferred_a or ''} {' '.join(self.preferred_b)}".strip() or None
        self.preferred_norm = self.normalizer(self.preferred) if self.preferred else None

        # variant
        self.variant_a = self._clean(variant_a)
        self.variant_a_norm = self.normalizer(self.variant_a) if self.variant_a else None
        self.variant_b = self._clean_list(variant_b)
        self.variant_b_norm = [self.normalizer(b) for b in self.variant_b]
        self.variant = f"{self.variant_a or ''} {' '.join(self.variant_b)}".strip() or None
        self.variant_norm = self.normalizer(self.variant) if self.variant else None

        self.identical = self.variant == self.preferred

    @staticmethod
    def _clean(value: str | None) -> str | None:
        value = (value or "").strip()
        return value or None

    @staticmethod
    def _clean_list(values: list[str]) -> list[str]:
        return [value.strip() for value in values if value and value.strip()]

    def json(self) -> dict[str, object]:

        j = {
            "id": self.id,
            "autType": self.aut_type,
            "ind1": self.ind1,
            "ind2": self.ind2,
            "authority": self.authority_id,
            "entryIndex": self.entry_index,
            "nVariants": self.n_variants,
            "identical": self.identical,
            "years": self.years,
            "preferred": self.preferred,
            "variant": self.variant,
            "preferredA": self.preferred_a,
            "variantA": self.variant_a,
            "preferredNorm": self.preferred_norm,
            "variantNorm": self.variant_norm,
            "preferredANorm": self.preferred_a_norm,
            "variantANorm": self.variant_a_norm,
        }

        # all the b's
        for name, values in [
            ("preferredB", self.preferred_b),
            ("variantB", self.variant_b),
            ("preferredBNorm", self.preferred_b_norm),
            ("variantBNorm", self.variant_b_norm),
        ]:
            j[f"{name}_list"] = values
            j[name] = values[0] if values else ""

        return j