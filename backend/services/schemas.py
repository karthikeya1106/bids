"""
Schema registry.

Each supported analysis has its own target-field template instead of the old
single sales schema. Fields carry a semantic type, aliases used by the mapping
engine, and optional derivation rules. Schemas are templates: nothing is
required unless the analysis genuinely cannot run without it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

# Semantic types used for mapping/validation. They are intentionally coarse:
# the engine only needs to know what a value must behave like.
NUMERIC = "numeric"
DATETIME = "datetime"
IDENTIFIER = "identifier"
CATEGORICAL = "categorical"
TEXT = "text"
BOOLEAN = "boolean"


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    description: str
    dtype: str
    required: bool = False
    aliases: tuple[str, ...] = ()
    # A technical row identifier may be generated when the source has none. It
    # is always labelled as generated and never used as a business measurement.
    allow_generated: bool = False
    # Derivation rule id; derived fields are computed from mapped source fields
    # and never guessed.
    derive: Optional[str] = None
    # Column that can act as a supervised-learning target.
    target: bool = False
    # Grouping/feature hint used by the adaptive engine.
    role: str = "feature"  # feature | time | target | identifier | measure


@dataclass
class DatasetSchema:
    id: str
    label: str
    description: str
    fields: list[FieldSpec]
    default_task: str = "eda"
    default_target: Optional[str] = None
    domain_keywords: tuple[str, ...] = ()
    custom: bool = False

    def field_map(self) -> dict[str, FieldSpec]:
        return {spec.key: spec for spec in self.fields}

    def field(self, key: str) -> Optional[FieldSpec]:
        return self.field_map().get(key)

    def mapped_fields(self) -> list[FieldSpec]:
        return [spec for spec in self.fields if spec.derive is None]

    def required_fields(self) -> list[FieldSpec]:
        return [spec for spec in self.fields if spec.required]

    def to_payload(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "default_task": self.default_task,
            "fields": [
                {
                    "key": spec.key,
                    "label": spec.label,
                    "description": spec.description,
                    "dtype": spec.dtype,
                    "required": spec.required,
                    "aliases": list(spec.aliases),
                    "derive": spec.derive,
                    "target": spec.target,
                    "role": spec.role,
                    "allow_generated": spec.allow_generated,
                }
                for spec in self.fields
            ],
        }


SALES = DatasetSchema(
    id="sales",
    label="Sales & Revenue Analytics",
    description=(
        "Transactional sales or order history. Powers the Executive Dashboard, "
        "Behavior, Segmentation, Root Cause, Forecasting and the deep Analysis Report."
    ),
    default_task="forecast",
    default_target="sales",
    domain_keywords=(
        "order", "invoice", "sales", "revenue", "profit", "discount",
        "quantity", "product", "sku", "ship", "category", "retail",
    ),
    fields=[
        FieldSpec(
            "order_id", "Order / Transaction ID",
            "Unique identifier of the transaction. Counted as a distinct order.",
            IDENTIFIER, aliases=(
                "order_id", "orderid", "order_no", "order_number", "invoice",
                "invoice_no", "invoice_number", "transaction_id", "txn_id",
                "transaction_no", "receipt_id", "row_id", "record_id",
                "order_key", "order_code",
            ),
            allow_generated=True, role="identifier",
        ),
        FieldSpec(
            "order_date", "Order Date",
            "Date the transaction happened. Required to build any timeline.",
            DATETIME, required=True, aliases=(
                "order_date", "orderdate", "date", "purchase_date",
                "transaction_date", "invoice_date", "order_ts", "created_at",
                "sale_date", "shipped_date", "timestamp",
            ), role="time",
        ),
        FieldSpec(
            "customer_id", "Customer ID",
            "Identifier of the buying customer, used for cohorts and retention.",
            IDENTIFIER, aliases=(
                "customer_id", "customerid", "customer_no", "customer_number",
                "cust_id", "client_id", "buyer_id", "account_id", "account_no",
                "member_id", "user_id", "userid", "subscriber_id",
            ), role="identifier",
        ),
        FieldSpec(
            "sales", "Sales / Revenue",
            "Revenue for the transaction. Drives every revenue metric.",
            NUMERIC, required=True, aliases=(
                "sales", "revenue", "sales_amount", "sale_amount", "net_sales",
                "gross_sales", "total_sales", "total_amount", "amount",
                "line_total", "turnover", "income", "mrr", "arr", "value",
                "salesvalue", "grand_total",
            ), target=True, role="measure",
        ),
        FieldSpec(
            "profit", "Profit",
            "Profit or margin for the transaction. Enables margin analysis.",
            NUMERIC, aliases=(
                "profit", "net_profit", "gross_profit", "profit_amount",
                "gross_margin", "net_income", "earnings", "gain",
            ), role="measure",
        ),
        FieldSpec(
            "quantity", "Quantity",
            "Units sold in the transaction.",
            NUMERIC, aliases=(
                "quantity", "qty", "units", "units_sold", "order_qty",
                "quantity_ordered", "items", "item_count", "count",
            ), role="measure",
        ),
        FieldSpec(
            "discount", "Discount",
            "Discount applied to the transaction (ratio or percentage).",
            NUMERIC, aliases=(
                "discount", "discount_pct", "discount_rate", "disc", "rebate",
                "markdown", "discount_amount",
            ), role="measure",
        ),
        FieldSpec(
            "ship_date", "Ship Date",
            "Date the order shipped, used for fulfilment lag.",
            DATETIME, aliases=(
                "ship_date", "shipping_date", "shipped_date", "dispatch_date",
                "delivery_date",
            ), role="time",
        ),
        FieldSpec(
            "customer_name", "Customer Name",
            "Human readable customer name.",
            TEXT, aliases=(
                "customer_name", "customer", "client_name", "full_name",
                "name", "buyer", "account_name",
            ),
        ),
        FieldSpec(
            "segment", "Customer Segment",
            "Market or customer segment (e.g. Consumer, Corporate).",
            CATEGORICAL, aliases=(
                "segment", "customer_segment", "market_segment", "customer_type",
                "client_segment", "tier", "account_type",
            ),
        ),
        FieldSpec(
            "category", "Product Category",
            "Product or service category.",
            CATEGORICAL, aliases=(
                "category", "product_category", "product_type", "department",
                "dept", "line_of_business",
            ),
        ),
        FieldSpec(
            "sub_category", "Sub-Category",
            "Secondary product grouping.",
            CATEGORICAL, aliases=(
                "sub_category", "subcategory", "sub_cat", "product_sub_category",
                "sub_type", "subcategory_name",
            ),
        ),
        FieldSpec(
            "product_name", "Product Name",
            "Product, SKU or plan sold.",
            TEXT, aliases=(
                "product_name", "product", "item", "item_name", "description",
                "product_description", "sku", "sku_name", "plan_name",
            ),
        ),
        FieldSpec(
            "region", "Region",
            "Sales region or territory.",
            CATEGORICAL, aliases=(
                "region", "territory", "sales_region", "zone", "geography",
                "country", "continent", "market",
            ),
        ),
        FieldSpec(
            "city", "City",
            "Customer or shipping city.",
            CATEGORICAL, aliases=("city", "town", "municipality", "billing_city"),
        ),
        FieldSpec(
            "state", "State",
            "Customer or shipping state/province.",
            CATEGORICAL, aliases=(
                "state", "province", "state_province", "billing_state",
            ),
        ),
    ],
)

CHURN = DatasetSchema(
    id="churn",
    label="Customer Churn Analytics",
    description=(
        "One row per customer/subscriber with a churn label. Native churn "
        "analytics, segments and a supervised churn model — never sales revenue."
    ),
    default_task="classification",
    default_target="churn_status",
    domain_keywords=(
        "churn", "attrition", "tenure", "cancel", "retention", "plan",
        "contract", "subscription", "usage", "vmail", "account length",
        "international plan", "voice mail", "service calls", "day mins",
        "monthly charges", "total charges", "exited", "isactive",
        "internet", "broadband", "subscriber", "download", "upload",
        "bill", "tv", "movie", "service failure",
    ),
    fields=[
        FieldSpec(
            "subscriber_id", "Customer / Subscriber ID",
            "Identifier of the customer. Generated only when the file has none.",
            IDENTIFIER, aliases=(
                "customer_id", "customerid", "subscriber_id", "subscriberid",
                "customer_no", "account_id", "account_no", "user_id", "id",
                "client_id", "member_id",
            ), allow_generated=True, role="identifier",
        ),
        FieldSpec(
            "churn_status", "Churn Status",
            "Whether the customer left (Yes/1/Churned) or stayed. The churn label.",
            CATEGORICAL, required=True, aliases=(
                "churn", "churned", "churn_status", "churn_label", "is_churned",
                "exited", "attrition", "attrited", "cancel", "cancelled",
                "canceled", "left", "status", "isactive", "is_active",
                "retained", "subscription_status",
            ), target=True, role="target",
        ),
        FieldSpec(
            "tenure", "Customer Tenure",
            "How long the customer has been with the business (months or years — check the values).",
            NUMERIC, aliases=(
                "tenure", "account_length", "accountlength", "customer_tenure",
                "months", "months_active", "tenure_months", "account_age",
                "subscription_age", "subscriptionage", "subscription_length",
                "days_since_signup", "lifetime",
            ), role="measure",
        ),
        FieldSpec(
            "bill_avg", "Average Bill",
            "Average amount billed to the customer per period.",
            NUMERIC, aliases=(
                "bill_avg", "billavg", "avg_bill", "average_bill", "monthly_bill",
                "bill_amount", "average_monthly_bill", "bill",
            ), role="measure",
        ),
        FieldSpec(
            "remaining_contract", "Remaining Contract",
            "Remaining contract term (months or years as supplied by the source).",
            NUMERIC, aliases=(
                "reamining_contract", "remaining_contract", "remain_contract",
                "contract_remaining", "remaining_contract_months", "contract_time",
            ), role="measure",
        ),
        FieldSpec(
            "service_failures", "Service Failures",
            "Number of service failures or support escalations recorded.",
            NUMERIC, aliases=(
                "service_failure_count", "service_failures", "service_failure",
                "failure_count", "failures", "support_failures", "ticket_count",
            ), role="measure",
        ),
        FieldSpec(
            "download_avg", "Average Download",
            "Average download volume per period (unit as supplied by the source).",
            NUMERIC, aliases=(
                "download_avg", "avg_download", "download_average", "download",
                "download_volume", "download_usage",
            ), role="measure",
        ),
        FieldSpec(
            "upload_avg", "Average Upload",
            "Average upload volume per period (unit as supplied by the source).",
            NUMERIC, aliases=(
                "upload_avg", "avg_upload", "upload_average", "upload",
                "upload_volume", "upload_usage",
            ), role="measure",
        ),
        FieldSpec(
            "download_over_limit", "Download Over Limit",
            "Count or flag of periods where the download allowance was exceeded.",
            NUMERIC, aliases=(
                "download_over_limit", "over_limit", "over_limit_count",
                "download_excess", "exceeded_limit",
            ), role="measure",
        ),
        FieldSpec(
            "tv_subscriber", "TV Subscriber",
            "Whether the customer subscribes to the TV package.",
            CATEGORICAL, aliases=(
                "is_tv_subscriber", "tv_subscriber", "tv_subscription", "has_tv",
                "tv_plan",
            ),
        ),
        FieldSpec(
            "movie_subscriber", "Movie Package Subscriber",
            "Whether the customer subscribes to the movie package.",
            CATEGORICAL, aliases=(
                "is_movie_package_subscriber", "movie_package_subscriber",
                "movie_subscriber", "has_movie_package", "movie_plan",
            ),
        ),
        FieldSpec(
            "state", "State / Region",
            "Customer geography.",
            CATEGORICAL, aliases=("state", "province", "region", "geography"),
        ),
        FieldSpec(
            "area_code", "Area Code",
            "Telecom area code or regional code.",
            CATEGORICAL, aliases=("area_code", "areacode", "area", "zone_code"),
        ),
        FieldSpec(
            "intl_plan", "International Plan",
            "Whether the customer has an international plan.",
            CATEGORICAL, aliases=(
                "international_plan", "intl_plan", "intlplan", "international",
            ),
        ),
        FieldSpec(
            "voicemail_plan", "Voicemail Plan",
            "Whether the customer has a voicemail plan.",
            CATEGORICAL, aliases=(
                "voice_mail_plan", "voicemail_plan", "vmail_plan", "vm_plan",
            ),
        ),
        FieldSpec(
            "voicemail_msgs", "Voicemail Messages",
            "Number of voicemail messages received.",
            NUMERIC, aliases=(
                "number_vmail_messages", "number_vmail_message",
                "vmail_messages", "voicemail_messages", "vmail_message",
                "vm_messages", "voicemail_msgs",
            ), role="measure",
        ),
        FieldSpec(
            "day_mins", "Day Minutes",
            "Total daytime usage minutes.",
            NUMERIC, aliases=(
                "total_day_minutes", "day_minutes", "day_mins", "day_min",
            ), role="measure",
        ),
        FieldSpec(
            "day_calls", "Day Calls",
            "Number of daytime calls.",
            NUMERIC, aliases=("total_day_calls", "day_calls", "day_call"),
            role="measure",
        ),
        FieldSpec(
            "day_charge", "Day Charges",
            "Daytime usage charges.",
            NUMERIC, aliases=(
                "total_day_charge", "day_charge", "day_charges",
                "daytime_charge",
            ), role="measure",
        ),
        FieldSpec(
            "eve_mins", "Evening Minutes",
            "Total evening usage minutes.",
            NUMERIC, aliases=(
                "total_eve_minutes", "eve_minutes", "eve_mins",
                "total_evening_minutes", "evening_minutes",
            ), role="measure",
        ),
        FieldSpec(
            "eve_calls", "Evening Calls",
            "Number of evening calls.",
            NUMERIC, aliases=(
                "total_eve_calls", "eve_calls", "total_evening_calls",
                "evening_calls",
            ), role="measure",
        ),
        FieldSpec(
            "eve_charge", "Evening Charges",
            "Evening usage charges.",
            NUMERIC, aliases=(
                "total_eve_charge", "eve_charge", "total_evening_charge",
                "evening_charge",
            ), role="measure",
        ),
        FieldSpec(
            "night_mins", "Night Minutes",
            "Total night usage minutes.",
            NUMERIC, aliases=(
                "total_night_minutes", "night_minutes", "night_mins",
            ), role="measure",
        ),
        FieldSpec(
            "night_calls", "Night Calls",
            "Number of night calls.",
            NUMERIC, aliases=("total_night_calls", "night_calls"), role="measure",
        ),
        FieldSpec(
            "night_charge", "Night Charges",
            "Night usage charges.",
            NUMERIC, aliases=(
                "total_night_charge", "night_charge", "night_charges",
            ), role="measure",
        ),
        FieldSpec(
            "intl_mins", "International Minutes",
            "Total international usage minutes.",
            NUMERIC, aliases=(
                "total_intl_minutes", "intl_minutes", "intl_mins",
                "international_minutes",
            ), role="measure",
        ),
        FieldSpec(
            "intl_calls", "International Calls",
            "Number of international calls.",
            NUMERIC, aliases=(
                "total_intl_calls", "intl_calls", "international_calls",
            ), role="measure",
        ),
        FieldSpec(
            "intl_charge", "International Charges",
            "International usage charges.",
            NUMERIC, aliases=(
                "total_intl_charge", "intl_charge", "international_charge",
            ), role="measure",
        ),
        FieldSpec(
            "service_calls", "Customer Service Calls",
            "Number of calls to customer service.",
            NUMERIC, aliases=(
                "customer_service_calls", "service_calls", "cust_serv_calls",
                "support_calls", "number_customer_service_calls",
            ), role="measure",
        ),
        FieldSpec(
            "total_charge", "Total Charges",
            "Total charges billed to the customer.",
            NUMERIC, aliases=(
                "total_charge", "total_charges", "monthly_charges",
                "total_revenue", "lifetime_value",
            ), role="measure",
        ),
        FieldSpec(
            "total_charge_derived", "Total Charges (derived)",
            "Sum of the mapped day, evening, night and international charges.",
            NUMERIC, derive="sum_charges", role="measure",
        ),
    ],
)

INVENTORY = DatasetSchema(
    id="inventory",
    label="Inventory & Demand Analytics",
    description=(
        "Stock levels and demand observations per product and period. Powers "
        "demand forecasting and reorder diagnostics."
    ),
    default_task="forecast",
    default_target="units_sold",
    domain_keywords=(
        "inventory", "stock", "warehouse", "supplier", "reorder", "demand",
        "units_sold", "on_hand", "sku", "lead_time", "restock",
    ),
    fields=[
        FieldSpec(
            "product_id", "Product ID", "Product or SKU identifier.",
            IDENTIFIER, aliases=(
                "product_id", "sku", "sku_id", "item_id", "product_code",
            ), role="identifier",
        ),
        FieldSpec(
            "product_name", "Product Name", "Product description.",
            TEXT, aliases=("product_name", "product", "item", "item_name", "description"),
        ),
        FieldSpec(
            "observation_date", "Observation Date",
            "Date of the stock/demand observation.",
            DATETIME, required=True, aliases=(
                "date", "observation_date", "snapshot_date", "order_date",
                "transaction_date", "period", "week", "month",
            ), role="time",
        ),
        FieldSpec(
            "stock_qty", "Stock Quantity", "Units available on hand.",
            NUMERIC, aliases=(
                "stock", "stock_qty", "inventory", "inventory_level",
                "on_hand", "quantity_on_hand", "available_stock", "closing_stock",
            ), role="measure",
        ),
        FieldSpec(
            "units_sold", "Demand / Units Sold",
            "Units sold or consumed in the period — the demand measure.",
            NUMERIC, aliases=(
                "units_sold", "demand", "units", "quantity_sold", "sold",
                "sales_qty", "consumption", "units_shipped",
            ), target=True, role="measure",
        ),
        FieldSpec(
            "unit_cost", "Unit Cost", "Cost per unit.",
            NUMERIC, aliases=(
                "unit_cost", "cost", "cost_per_unit", "purchase_price",
            ), role="measure",
        ),
        FieldSpec(
            "supplier", "Supplier", "Supplier name.",
            CATEGORICAL, aliases=("supplier", "vendor", "supplier_name"),
        ),
        FieldSpec(
            "warehouse", "Warehouse", "Warehouse or location.",
            CATEGORICAL, aliases=(
                "warehouse", "location", "site", "distribution_center",
            ),
        ),
        FieldSpec(
            "region", "Region", "Geographic region.",
            CATEGORICAL, aliases=("region", "territory", "market", "country"),
        ),
    ],
)

FINANCIAL = DatasetSchema(
    id="financial",
    label="Financial Analytics",
    description=(
        "Income, expenses and profit by period, account or department. Powers "
        "financial trend and expense analysis."
    ),
    default_task="forecast",
    default_target="revenue",
    domain_keywords=(
        "expense", "income", "revenue", "budget", "ledger", "account",
        "debit", "credit", "fiscal", "accounting", "balance_sheet",
        "department", "profit", "cost_center",
    ),
    fields=[
        FieldSpec(
            "transaction_id", "Transaction ID", "Unique transaction reference.",
            IDENTIFIER, aliases=(
                "transaction_id", "txn_id", "entry_id", "journal_id",
                "reference", "voucher_no",
            ), allow_generated=True, role="identifier",
        ),
        FieldSpec(
            "transaction_date", "Transaction Date",
            "Posting or transaction date.",
            DATETIME, required=True, aliases=(
                "transaction_date", "date", "posting_date", "entry_date",
                "period", "fiscal_period", "month",
            ), role="time",
        ),
        FieldSpec(
            "revenue", "Revenue / Income", "Revenue or income amount.",
            NUMERIC, required=True, aliases=(
                "revenue", "income", "credit", "total_revenue", "sales",
                "amount", "inflow",
            ), target=True, role="measure",
        ),
        FieldSpec(
            "expenses", "Expenses", "Expense amount.",
            NUMERIC, aliases=(
                "expenses", "expense", "cost", "debit", "outflow", "spend",
            ), role="measure",
        ),
        FieldSpec(
            "profit", "Profit", "Net profit amount.",
            NUMERIC, aliases=(
                "profit", "net_profit", "net_income", "earnings", "profit_loss",
            ), role="measure",
        ),
        FieldSpec(
            "account", "Account", "Ledger account or category.",
            CATEGORICAL, aliases=(
                "account", "account_name", "category", "ledger_account",
                "gl_account",
            ),
        ),
        FieldSpec(
            "department", "Department / Business Unit",
            "Department or cost centre.",
            CATEGORICAL, aliases=(
                "department", "dept", "business_unit", "division", "cost_center",
            ),
        ),
        FieldSpec(
            "profit_margin", "Profit Margin (derived)",
            "Profit divided by revenue, computed only when both exist.",
            NUMERIC, derive="profit_margin", role="measure",
        ),
    ],
)

MARKETING = DatasetSchema(
    id="marketing",
    label="Marketing & Campaign Analytics",
    description=(
        "Campaign results by date and channel. Powers spend efficiency and "
        "conversion analysis."
    ),
    default_task="forecast",
    default_target="conversions",
    domain_keywords=(
        "campaign", "channel", "impressions", "clicks", "ctr", "conversions",
        "ad_spend", "reach", "engagement", "creative", "ad_group",
    ),
    fields=[
        FieldSpec(
            "campaign_id", "Campaign ID", "Campaign identifier.",
            IDENTIFIER, aliases=(
                "campaign_id", "campaign", "ad_id", "ad_group_id", "campaign_code",
            ), role="identifier",
        ),
        FieldSpec(
            "date", "Date", "Reporting date of the campaign activity.",
            DATETIME, required=True, aliases=(
                "date", "report_date", "day", "period", "week", "month",
            ), role="time",
        ),
        FieldSpec(
            "channel", "Channel", "Marketing channel or platform.",
            CATEGORICAL, aliases=(
                "channel", "platform", "source", "medium", "network", "publisher",
            ),
        ),
        FieldSpec(
            "spend", "Spend", "Amount spent.",
            NUMERIC, required=True, aliases=(
                "spend", "cost", "ad_spend", "media_spend", "budget", "amount",
            ), role="measure",
        ),
        FieldSpec(
            "impressions", "Impressions", "Ad impressions served.",
            NUMERIC, aliases=("impressions", "impression", "views", "reach"),
            role="measure",
        ),
        FieldSpec(
            "clicks", "Clicks", "Clicks generated.",
            NUMERIC, aliases=("clicks", "click", "sessions", "visits"), role="measure",
        ),
        FieldSpec(
            "conversions", "Conversions", "Conversions or leads attributed.",
            NUMERIC, aliases=(
                "conversions", "conversion", "leads", "signups", "purchases",
                "orders",
            ), target=True, role="measure",
        ),
        FieldSpec(
            "revenue", "Attributed Revenue", "Revenue attributed to the activity.",
            NUMERIC, aliases=(
                "revenue", "sales", "attributed_revenue", "roas_revenue", "value",
            ), role="measure",
        ),
        FieldSpec(
            "segment", "Audience Segment", "Target audience segment.",
            CATEGORICAL, aliases=("segment", "audience", "target_audience", "persona"),
        ),
        FieldSpec(
            "ctr", "CTR (derived)", "Clicks divided by impressions.",
            NUMERIC, derive="click_through_rate", role="measure",
        ),
        FieldSpec(
            "roas", "ROAS (derived)", "Revenue divided by spend.",
            NUMERIC, derive="return_on_ad_spend", role="measure",
        ),
    ],
)

HR = DatasetSchema(
    id="hr",
    label="HR & Employee Analytics",
    description=(
        "Employee records. Supports attrition (classification), compensation "
        "analysis and workforce segmentation — no sales metrics."
    ),
    default_task="eda",
    domain_keywords=(
        "employee", "staff", "attrition", "salary", "hire", "headcount",
        "job_role", "performance", "department", "overtime", "promotion",
    ),
    fields=[
        FieldSpec(
            "employee_id", "Employee ID", "Employee identifier.",
            IDENTIFIER, aliases=(
                "employee_id", "employee_number", "emp_id", "staff_id", "id",
            ), allow_generated=True, role="identifier",
        ),
        FieldSpec(
            "department", "Department", "Department or team.",
            CATEGORICAL, aliases=(
                "department", "dept", "team", "division", "business_unit",
            ),
        ),
        FieldSpec(
            "role", "Job Role", "Job title or role.",
            CATEGORICAL, aliases=(
                "job_role", "role", "title", "job_title", "position",
            ),
        ),
        FieldSpec(
            "tenure", "Tenure", "Years or months with the company.",
            NUMERIC, aliases=(
                "tenure", "years_at_company", "years_company", "months_at_company",
                "service_length",
            ), role="measure",
        ),
        FieldSpec(
            "salary", "Salary", "Monthly or annual salary.",
            NUMERIC, aliases=("salary", "monthly_income", "income", "pay", "compensation"),
            target=True, role="measure",
        ),
        FieldSpec(
            "attrition", "Attrition", "Whether the employee left (Yes/No).",
            CATEGORICAL, aliases=(
                "attrition", "left", "resigned", "terminated", "exited",
                "employee_status", "status",
            ), target=True, role="target",
        ),
        FieldSpec(
            "performance", "Performance Rating", "Performance score or rating.",
            NUMERIC, aliases=(
                "performance", "performance_rating", "rating", "score",
                "performance_score",
            ), role="measure",
        ),
        FieldSpec(
            "gender", "Gender", "Employee gender.",
            CATEGORICAL, aliases=("gender", "sex"),
        ),
        FieldSpec(
            "age", "Age", "Employee age.",
            NUMERIC, aliases=("age", "employee_age"),
        ),
    ],
)

GENERIC = DatasetSchema(
    id="generic",
    label="General / Exploratory Dataset",
    description=(
        "No business-specific template. Every column is kept as-is and analysed "
        "with profiling, distributions, correlations and optional modelling."
    ),
    default_task="eda",
    domain_keywords=(),
    fields=[],
)

CUSTOM = DatasetSchema(
    id="custom",
    label="Custom Mapping",
    description=(
        "Define the target fields yourself. Each field can be required or "
        "optional and typed as numeric, date, identifier or category."
    ),
    default_task="eda",
    domain_keywords=(),
    custom=True,
    fields=[],
)

SCHEMAS: dict[str, DatasetSchema] = {
    schema.id: schema for schema in (SALES, CHURN, INVENTORY, FINANCIAL, MARKETING, HR, GENERIC, CUSTOM)
}

# Schemas whose records are materialised into the native sales/churn tables.
NATIVE_SCHEMAS = {"sales", "churn"}

DTYPE_LABEL = {
    NUMERIC: "Number",
    DATETIME: "Date",
    IDENTIFIER: "Identifier",
    CATEGORICAL: "Category",
    TEXT: "Text",
    BOOLEAN: "Yes / No",
}


def get_schema(schema_id: str | None, custom_fields: Optional[Iterable[dict]] = None) -> DatasetSchema:
    """Resolve a schema id; custom schemas are built from the supplied fields."""
    if schema_id == CUSTOM.id and custom_fields:
        return build_custom_schema(custom_fields)
    return SCHEMAS.get(schema_id or "generic", GENERIC)


def build_custom_schema(fields: Iterable[dict]) -> DatasetSchema:
    specs: list[FieldSpec] = []
    for index, raw in enumerate(fields):
        key = str(raw.get("key") or raw.get("name") or f"field_{index + 1}").strip()
        key = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in key.lower()) or f"field_{index + 1}"
        dtype = str(raw.get("dtype") or NUMERIC).lower()
        if dtype not in {NUMERIC, DATETIME, IDENTIFIER, CATEGORICAL, TEXT, BOOLEAN}:
            dtype = CATEGORICAL
        specs.append(
            FieldSpec(
                key=key,
                label=str(raw.get("label") or key.replace("_", " ").title()),
                description=str(raw.get("description") or "User-defined field."),
                dtype=dtype,
                required=bool(raw.get("required")),
                aliases=tuple(raw.get("aliases") or ()),
                target=bool(raw.get("target")),
                role="target" if raw.get("target") else "feature",
            )
        )
    return DatasetSchema(
        id=CUSTOM.id,
        label=CUSTOM.label,
        description=CUSTOM.description,
        fields=specs,
        default_task="eda",
        custom=True,
    )


def derived_fields_for(schema: DatasetSchema) -> list[FieldSpec]:
    return [spec for spec in schema.fields if spec.derive]
