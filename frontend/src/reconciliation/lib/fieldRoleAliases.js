// Deterministic Mapping needs to know which confirmed field-mapping row is
// the product/material pairing, which is the plant/location pairing, and so
// on — regardless of what the source or target actually calls that column.
// Live Fetch (SAP/IBP) gets this for free because the API's field names are
// always literally "Material"/"ProductionPlant"/"PRDID"/"LOCID". Excel
// headers vary ("SKU", "Material Code", "Plant ID", ...), so this module
// recognizes the same canonical roles from common header variations. See
// MappingEditor's "Business Field" column for the manual-override path when
// a header isn't recognized (or is recognized wrong).
export const FIELD_ROLES = {
  PRODUCT: "product",
  LOCATION: "location",
  DATE: "date",
  QUANTITY: "quantity",
};

const ROLE_LABELS = {
  product: "Product / Material",
  location: "Plant / Location",
  date: "Date / Period",
  quantity: "Quantity",
};

export function fieldRoleLabel(role) {
  return ROLE_LABELS[role] ?? role;
}

// Aliases are matched against a normalized (lowercase, letters+digits only)
// form of the column name, so "Material Code", "material_code", and
// "MaterialCode" all match the same "materialcode" entry. Includes the
// canonical SAP/IBP names so identical detection logic covers Live Fetch too.
const ROLE_ALIASES = {
  product: [
    "material", "materialcode", "materialnumber", "materialid",
    "materialdescription", "sku", "itemcode", "itemid", "itemnumber",
    "productid", "prdid", "productcode", "product",
  ],
  location: [
    "plant", "plantcode", "plantid", "productionplant",
    "location", "locationcode", "locationid", "locid",
    "site", "sitecode", "facility",
  ],
  date: [
    "date", "period", "periodid", "periodid0tstamp",
    "requesteddeliverydate", "deliverydate", "transactiondate", "orderdate",
  ],
  quantity: [
    "quantity", "qty", "requestedquantity", "salesorderrequest",
    "salesqty", "orderqty",
  ],
};

function normalize(name) {
  return String(name ?? "").toLowerCase().replace(/[^a-z0-9]/g, "");
}

// Checks the source and target column names against every role's alias list,
// returning the first role either name matches (source checked first).
// Returns null when neither name is recognized.
export function detectFieldRole(sourceCol, targetCol) {
  const candidates = [normalize(sourceCol), normalize(targetCol)];
  for (const [role, aliases] of Object.entries(ROLE_ALIASES)) {
    if (aliases.some((alias) => candidates.includes(alias))) return role;
  }
  return null;
}
