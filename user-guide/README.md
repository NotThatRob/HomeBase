# HomeBase User Guide

HomeBase helps a household track important possessions, documents, service
history, recurring costs, fuel, maintenance tasks, and ownership costs.

This guide is for people using the app day to day, plus household admins who
need a plain-language overview of safe deployment settings. Detailed developer
setup and test instructions live in the main project README.

## Start Here

1. [Getting Started](getting-started.md)
2. [Assets and Inventory](assets-and-inventory.md)
3. [Documents, Service, and Maintenance](documents-service-maintenance.md)
4. [Costs, Fuel, and Ownership](costs-fuel-ownership.md)
5. [Search, Settings, and Access](search-settings-access.md)
6. [Admin and Deployment Safety](admin-deployment-safety.md)

## Common Tasks

- **Add something you own**: go to **Inventory** → **New Asset**.
- **Upload a manual or receipt**: open an asset → use **Documents**.
- **Log repair or maintenance work**: open an asset → **Log Service**.
- **Add insurance, registration, or subscriptions**: open an asset →
  **Recurring Costs** → **Add Cost**.
- **Log fuel quickly**: use the fuel icon in the top bar or **Log Fuel** on the
  dashboard.
- **See what an asset costs you**: open an asset → **Cost of Ownership**.
- **Find something fast**: use the search box in the top bar.
- **Deploy safely**: use the production Docker + Caddy path and follow
  [Admin and Deployment Safety](admin-deployment-safety.md).

## Navigation

- **Dashboard**: overview, quick actions, upcoming maintenance, financial cards,
  charts, and recent activity.
- **Inventory**: all active assets, with category filters.
- **Asset detail**: the main workspace for a single item.
- **Settings**: profile, password, and admin user management.
- **Deployment docs**: safe self-hosting guidance for household admins.

## Notes

- Personal assets are visible only to the user who created them.
- Shared assets are visible to the household.
- Retired assets are hidden from the default inventory list but can still be
  shown with the retired filter.
- Recurring costs are projected obligations. They are not counted as already
  spent in tracked totals.
