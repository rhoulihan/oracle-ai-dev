-- Copyright (c) 2026 Oracle and/or its affiliates.
-- JSON Relational Duality view: the order document projected over the canonical
-- tables. The items array projects order_item_id (the full child PK) — omitting
-- it triggers ORA-40477 on read on 23.26.2 (gap-3 runtime finding).
CREATE OR REPLACE JSON RELATIONAL DUALITY VIEW order_dv AS
orders @insert @update @delete
{
  _id       : order_id
  orderedAt : ordered_at
  total     : total
  customer  : customer @noinsert @update @nodelete
  {
    customerId : customer_id
    name       : name
  }
  items : order_item @insert @update @delete
  [ {
      orderItemId : order_item_id
      menuItemId  : menu_item_id
      quantity    : quantity
      unitPrice   : unit_price
  } ]
};
