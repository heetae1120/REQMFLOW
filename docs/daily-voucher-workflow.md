# Daily voucher work table

The Actual Shipping workspace now opens on **전표 작업표**. Confirm actual
shipments through the existing shipment screen first; generating a WeKeep
request or obtaining an invoice alone does not create a voucher shipment.
Select the shipment date range and the separate voucher date, then review
seller, item code/name, shipped quantity, amount and confirmation status.
The initial date range is the last seven days. Previously generated rows are
visible by default with an explicit exported status and are read-only.
Unconfirmed requests appear by request date but cannot be exported; selected
requests can be confirmed with an explicitly entered actual shipment date.
Unmapped SmartStore rows display the original product, quantity and amount
and open the existing matching dialog when double-clicked.
Search includes order numbers and recipients; these remain in the stored
source data and the amount dialog rather than taking space in the main table.

**선택 주문 금액 입력** edits the total merchandise amount (excluding delivery)
and the total amount for each component, not its unit price. Amounts must be
non-negative integer won and must add up exactly. Single items follow the
entered total. Partial shipments are edited independently and never supply
reusable full-set price templates.

## Live allocation feedback and amount review

The voucher amount dialog shows the target merchandise total, current entered
sum and remaining amount while typing. For a 36,900 won target, entering 28,500
won with the other entry empty shows 8,400 won remaining. The sum turns green
with `금액 일치` at 36,900 won; excess is red and remaining is amber. Blank
component entries count as zero for feedback only. Confirmation requires all
entries to contain non-negative integer won and the sum to equal the target.
The older component allocation dialog also shows the remaining amount.

Price review uses verified item codes or explicitly assigned colour families,
component quantities per set, seller and seller account. Product/option name
similarity remains a candidate aid and does not approve a price comparison.
Confirmed full-order history up to the shipment day supplies known per-set
prices; future days, other configurations and partial shipments are excluded.
Within-day history consists of orders already confirmed when the review runs.
No inferred campaign or discount classification is applied.

The work table highlights a price not present in that history, conflicting
component allocations for the same total, and a full-order voucher total that
differs from the source merchandise total. It shows the source/entered amounts
and their difference. Such differences require an operator reason in the amount
dialog before confirmation. A matching allocation sum alone does not approve
a difference from the source. ERP preview and file generation both block
unreviewed differences for the selected orders.

Review signatures, reasons, warnings and UTC confirmation times are saved under
`voucher:v1:review:` in mappings and accompany existing workspace sync/backup.
Events retain the review detail. Changes to source monetary fields, composition,
quantities or allocation invalidate an old review; recipient/address changes
do not. Source-mismatched history without a valid review does not establish a
price reference. Partial shipments retain the existing independent amount
entry behavior and are not compared to a complete order's source total.

## Reuse between colours

The versioned `voucher_families.json` explicitly maps colour SKUs to model
families. Initial assignments were prepared from active Shipping standard
names by removing only a known terminal colour. Model, capacity and length
remain distinct. Unassigned SKUs do not share prices. **색상 공유 그룹** lets
operators review or override each active SKU's model family; an empty value
disables sharing. Overrides sync as reserved mapping rows. The amount dialog
displays the family for inspection. Actual item codes and colour-specific
names are never replaced by the family key.

A template key includes seller, seller account, product families, quantities
per ordered set and merchandise amount per set. Allocation totals are stored
as exact fractions per set, and are applied only when the resulting won
amounts are integral and sum to the source merchandise total. Multiple
components from the same family are ambiguous and cannot reuse a template.
Different templates for the same key also require manual entry; no arbitrary
template is chosen. A changed selling price requires a new confirmed split.

Saving an allocation can store its template and apply it to eligible pending
sets in the selected period. **기존 세트 금액 적용** also learns historical
confirmed splits from the older screen, including previously exported sets.
The opt-out checkbox prevents learning that order's allocation later.
Partial shipments, mapping errors and previously exported orders are excluded
from application. Different order quantities scale the same per-set split.

Templates, opt-outs and explicit fee overrides use the reserved `voucher:v1:`
namespace of the existing `mappings` table. Regular product lookup uses exact
JSON order-mapping keys and cannot select these entries. The existing backup,
workspace snapshot and row-level Supabase sync therefore carry these rules
without an additional server whitelist or table migration.

## Delivery fees and file generation

The fee identity is seller + seller account + order number. Bundle numbers
no longer control new voucher fees. Delivery is charged on the first voucher
containing that order and is recorded in `fees` even when zero. Repeated
positive amounts are deduplicated; a zero on another source row does not
cancel a positive amount. Conflicting positive values block output until the
operator sets the order's explicit fee in **배송비 검수**. The lookup includes
other stored rows of the order to support partial shipment.

General, SmartStore and ESM voucher sources use the same fee collector.
Amounts use each source's parsed `shipping` value; a missing source column
means zero and can be set in the fee review dialog. Existing seller-specific
parsing is retained: no universal island-fee addition or discount subtraction
is introduced. Legacy bundle fee records still prevent charging those orders
again. Legacy re-download preserves one fee for a shared legacy bundle.

**전표 미리보기** runs the same selection, validation, integer-won splitting,
fee collection and aggregation as actual export but creates no artifact,
fee or ERP assignment. The preview shows total including delivery. Actual
export fills voucher date and item name, aggregates equal customer/item/
warehouse/unit-price rows and records each included source as exported.
Re-download regenerates the original selection and its assigned fees; it
does not create another ERP assignment. ERP registration on the external
site remains a separate manual operation.

Tests cover colour reuse and quantity scaling, changed price/model/seller,
conflicting allocations, exact sums and rollback, fee override and workspace
transfer, preview immutability, SmartStore/ESM fees, partial export, legacy
re-download and the actual Tk work-table/preview views.
