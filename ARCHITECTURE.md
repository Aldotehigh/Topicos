# Project structure

MyRestaurant separates the mobile interface from the restaurant API. The mobile application sends authenticated HTTP requests; the server validates permissions and business rules before reading or changing the database.

## Mobile application

| Folder | Responsibility |
| --- | --- |
| `src/app/(auth)` | Sign-in and registration screens. |
| `src/app/(app)` | Menu, product form/details, favorites, orders, reservations, settings and operator screens. |
| `src/components` | Reusable controls, product cards, order cards, forms and selection panels. |
| `src/context` | Shared authentication, cart, orders and appearance/language state. |
| `src/services` | Typed requests to catalogue, orders, checkout and other API endpoints. |
| `src/types` | TypeScript contracts for the data used by screens and services. |
| `src/utils` | Authentication helpers, token storage, translations, saved preferences and formatting. |
| `src/constants` | Shared visual values and configuration constants. |
| `assets` | Application icon, splash image, fonts and interface resources. |
| `plugins` | Expo configuration plugins for the iOS project. |
| `ios` | Native iOS application project. |

## Backend

| File or folder | Responsibility |
| --- | --- |
| `manage.py` | Entry point for Django commands. |
| `restaurant/settings.py` | Installed applications, database, authentication, permissions and media configuration. |
| `restaurant/urls.py` | Registers API routes and the administration site. |
| `restaurant/catalog/models.py` | Database entities, relationships and model constraints. |
| `serializers.py` | Validates request data and builds nested catalogue/profile responses. |
| `views.py` | Authentication, profile, catalogue CRUD, search, filters and favorites. |
| `permissions.py`, `roles.py` | Controls access for customers, owners and department managers. |
| `orders.py`, `order_choices.py`, `order_pricing.py` | Order creation, customization validation, workflow and pricing. |
| `reorder.py` | Builds repeat-order previews using current products, prices and customization options. |
| `checkout.py`, `business.py` | Payment review, receipts, inventory and sales summaries. |
| `reservations.py`, `promotions.py`, `supplies.py` | Reservation, promotion calendar and supply-request workflows. |
| `preferences.py` | Stores theme and language per authenticated user. |
| `admin.py` | Restaurant administration screens and filters. |
| `migrations` | Versioned changes to the database schema. |
| `test_*.py` | Automated checks for permissions, validation and restaurant workflows. |
| `fixtures/restaurant_menu.json` | Public catalogue data used to initialize the delivery package. |
| `media/cards` | Menu photographs referenced by products. |

## Example request flow

1. The customer signs in. The server returns a token stored securely on the phone.
2. A screen calls a typed service. The request includes the token in its authorization header.
3. Django selects the view, verifies the user role and validates the request.
4. Models provide or update the data. Serializers return JSON to the mobile application.
5. The screen updates its loading, success or error state.

When an order is placed, the server checks current product availability and customization options, calculates the price and saves the customer's allergy and food-preference notes with the order lines. Department managers see only their relevant preparation queue. Food preferences are customer features; theme and language are available to all roles.

## Presentation route

Demonstrate sign-in, catalogue search/filtering, product details, favorites, pagination and settings with a customer account. Use an authorized operator or administrator account for product management. Then show a nested product response in Postman and the corresponding model, serializer and view. Finish with the administration panel and automated tests.
