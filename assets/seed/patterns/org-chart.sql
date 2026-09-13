-- Copyright (c) 2026 Oracle and/or its affiliates.
-- Org-chart mini-domain (Tree pattern fixture): a self-referencing hierarchy.
CREATE TABLE IF NOT EXISTS employee (
  emp_id      NUMBER PRIMARY KEY,
  name        VARCHAR2(120 CHAR) NOT NULL,
  manager_id  NUMBER REFERENCES employee (emp_id)
);

DELETE FROM employee;
INSERT INTO employee (emp_id, name, manager_id) VALUES (1, 'CEO', NULL);
INSERT INTO employee (emp_id, name, manager_id) VALUES (2, 'VP Eng', 1);
INSERT INTO employee (emp_id, name, manager_id) VALUES (3, 'VP Sales', 1);
INSERT INTO employee (emp_id, name, manager_id) VALUES (4, 'Eng Mgr', 2);
INSERT INTO employee (emp_id, name, manager_id) VALUES (5, 'Engineer', 4);
INSERT INTO employee (emp_id, name, manager_id) VALUES (6, 'Sales Rep', 3);
COMMIT;
