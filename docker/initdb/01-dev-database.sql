-- Rulează o singură dată, când PostgreSQL își creează volumul (prima pornire).
--
-- Două baze de date separate:
--   aprovizionare      → aplicația din Docker (docker compose up), cu date demo generate
--                        automat la prima pornire, exact cum o vede un evaluator;
--   aprovizionare_dev  → dezvoltarea (runserver, teste), cu datele dezvoltatorului.
-- Separate, ca datele unuia să nu le blocheze sau amestece pe ale celuilalt.
CREATE DATABASE aprovizionare_dev OWNER aprovizionare;
