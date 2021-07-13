# Firstech Saleor Fork

This repository is a fork of [Saleor](https://github.com/mirumee/saleor.git). Typically you will want to clone this as
a sub-directory in your `ft-saleor-local` project.

## Working with upstream changes

After cloning this project, you will want to add the source project as your upstream remote:

    git remote add upstream https://github.com/mirumee/saleor.git

We are currently using **v3.0.0a15** of Saleor, which means that upstream changes will be available in the `3.0` branch.

TBD: how to upgrade to later versions of 3.0. Merge the tag into `ft-develop`?

## Provision Infrastructure on AWS

1. Edit the `copilot/api/manifest.yml` and `copilot/worker/manifest.yml` files and temporarily comment out the `secrets` section from the config.
1. Deploy the Copilot api service: `copilot svc deploy -n api`
1. Deploy the Copilot worker service: `copilot svc worker -n worker`
1. Run Terraform from the right directory in the `infrastructure-config` repository to deploy the auxillary infrastructure. (ex. `infrastructure-config/aws/accounts/dev-741267758119/us-west-2/saleor`)
1. Use the AWS console to find the DNS endpoint names for the Saleor Postgres Aurora database in RDS and the Saleor Redis cluster in ElastiCache.
1. Navigate to AWS CloudMap and manually register new instances for the `db` and `redis` services using the appropriate CNAMES from the Terraform resources.
1. Retrieve the `DATABASE_URL` value and the `SECRET_KEY` values from the AWS SSM parameter via the console (ex. `/saleor/dev/DATABASE_URL`, `/saleor/dev/SECRET_KEY`.
1. Run the Saleor application setup commands as Copilot tasks:
  1. `copilot task run --command "python3 manage.py migrate" --dockerfile ./Dockerfile --env-vars DATABASE_URL=<database-url-value>,SECRET_KEY=<secret-key-value> --follow --task-group-name saleor-db-migrate`
  1. (run other commands remotely as desired using a similar format)
1. Change the `manifest.yml` files for the `api` and `worker` Copilot services to reinstate the `secrets` definitions.
1. Redeploy both Copilot services.
1. Run any additional setup commands like generating statics, populating the database or setting a superuser via the ECS container directly using `copilot svc exec -n api` for a shell prompt.

**********

![Saleor Commerce - A GraphQL-first platform for perfectionists](https://user-images.githubusercontent.com/249912/71523206-4e45f800-28c8-11ea-84ba-345a9bfc998a.png)

<div align="center">
  <h1>Saleor Commerce</h1>
</div>

<div align="center">
  <strong>Customer-centric e-commerce on a modern stack</strong>
</div>

<div align="center">
  A headless, GraphQL-first e-commerce platform delivering ultra-fast, dynamic, personalized shopping experiences. Beautiful online stores, anywhere, on any device.
</div>

<br>

<div align="center">
  Join our active, engaged community: <br>
  <a href="https://saleor.io/">Website</a>
  <span> | </span>
  <a href="https://medium.com/saleor">Blog</a>
  <span> | </span>
  <a href="https://twitter.com/getsaleor">Twitter</a>
  <span> | </span>
  <a href="https://gitter.im/mirumee/saleor">Gitter</a>
  <span> | </span>
  <a href="https://spectrum.chat/saleor">Spectrum</a>
</div>

<br>

<div align="center">
  <a href="http://codecov.io/github/mirumee/saleor?branch=master">
    <img src="http://codecov.io/github/mirumee/saleor/coverage.svg?branch=master" alt="Codecov" />
  </a>
  <a href="https://docs.saleor.io/">
    <img src="https://img.shields.io/badge/docs-docs.saleor.io-brightgreen.svg" alt="Documentation" />
  </a>
  <a href="https://github.com/python/black">
    <img src="https://img.shields.io/badge/code%20style-black-000000.svg" alt="Code style: black">
  </a>
</div>

## Table of Contents

- [What makes Saleor special?](#what-makes-saleor-special)
- [Features](#features)
- [Installation](#installation)
- [Documentation](#documentation)
- [Demo](#demo)
- [Contributing](#contributing)
- [Translations](#translations)
- [Your feedback](#your-feedback)
- [License](#license)

## What makes Saleor special?

Saleor is a rapidly-growing open source e-commerce platform that has served high-volume companies from branches like publishing and apparel since 2012. Based on Python and Django, the latest major update introduces a modular front end powered by a GraphQL API and written with React and TypeScript.

## Features

- **PWA**: End users can shop offline for better sales and shopping experiences
- **GraphQL API**: Access all data from any web or mobile client using the latest technology
- **Headless commerce**: Build mobile apps, customize storefronts and externalize processes
- **UX and UI**: Designed for a user experience that rivals even the top commercial platforms
- **Dashboard**: Administrators have total control of users, processes, and products
- **Orders**: A comprehensive system for orders, dispatch, and refunds
- **Cart**: Advanced payment and tax options, with full control over discounts and promotions
- **Payments**: Flexible API architecture allows integration of any payment method. It comes with Braintree support out of the box.
- **Geo-adaptive**: Automatic localized pricing. Over 20 local languages. Localized checkout experience by country.
- **SEO**: Packed with features that get stores to a wider audience
- **Cloud**: Optimized for deployments using Docker
- **Analytics**: Server-side Google Analytics to report e-commerce metrics without affecting privacy

Saleor is free and always will be.
Help us out… If you love free stuff and great software, give us a star! 🌟

![Saleor Storefront - React-based PWA e-commerce storefront](https://user-images.githubusercontent.com/249912/71527146-5b6be280-28da-11ea-901d-eb76161a6bfb.png)
![Saleor Dashboard - Modern UI for managing your e-commerce](https://user-images.githubusercontent.com/249912/71523261-8a795880-28c8-11ea-98c0-6281ea37f412.png)

## Installation

Saleor requires Python 3.8, Node.js 10.0+, PostgreSQL and OS-specific dependency tools.

[See the Saleor docs](https://docs.saleor.io/docs/developer/installation) for step-by-step installation and deployment instructions.

Note:
The `master` branch is the development version of Saleor and it may be unstable. To use the latest stable version, download it from the [Releases](https://github.com/mirumee/saleor/releases/) page or switch to a release tag.

The current stable version is 2.11 and you should use this version for all three components:

- Saleor: https://github.com/mirumee/saleor/releases/tag/2.11.1
- Dashboard: https://github.com/mirumee/saleor-dashboard/releases/tag/2.11.1
- Storefront: https://github.com/mirumee/saleor-storefront/releases/tag/2.11.0

## Documentation

Saleor documentation is available here: [docs.saleor.io](https://docs.saleor.io)

To contribute, please see the [`mirumee/saleor-docs` repository](https://github.com/mirumee/saleor-docs/).

## Saleor Platform

The easiest way to run all components of Saleor (API, storefront and dashboard) together on your local machine is to use the [saleor-platform](https://github.com/mirumee/saleor-platform) project. Go to that repository for instructions on how to use it.

[View saleor-platform](https://github.com/mirumee/saleor-platform)

## Storefront

For PWA, single-page storefront go to the [saleor-storefront](https://github.com/mirumee/saleor-storefront) repository.

[View storefront demo](https://demo.saleor.io/)

## Dashboard

For dashboard go to the [saleor-dashboard](https://github.com/mirumee/saleor-dashboard) repository.

[View dashboard demo](https://demo.saleor.io/dashboard/)

## Demo

Want to see Saleor in action?

[View Storefront](https://demo.saleor.io/) | [View Dashboard (admin area)](https://demo.saleor.io/dashboard/)

Or launch the demo on a free Heroku instance.

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy)

Login credentials: `admin@example.com`/`admin`

## Contributing

We love your contributions and do our best to provide you with mentorship and support. If you are looking for an issue to tackle, take a look at issues labeled [`Help Wanted`](https://github.com/mirumee/saleor/issues?q=is%3Aopen+is%3Aissue+label%3A%22help+wanted%22).

If nothing grabs your attention, check [our roadmap](https://github.com/mirumee/saleor/projects/12) or come up with your feature. Just drop us a line or [open an issue](https://github.com/mirumee/saleor/issues/new) and we’ll work out how to handle it.

Get more details in our [Contributing Guide](https://docs.saleor.io/docs/developer/community/contributing).

## Legacy views

If you're interested in using the old version of Saleor, go the [legacy-views](https://github.com/mirumee/legacy-views) repository. It contains the 2.9.0 release, which includes Django-based views and HTML templates of Storefront 1.0 and Dashboard 1.0. Note: this version of Saleor is no longer officially maintained.

## Your feedback

Do you use Saleor as an e-commerce platform?
Fill out this short survey and help us grow. It will take just a minute, but mean a lot!

[Take a survey](https://mirumee.typeform.com/to/sOIJbJ)

## License

Disclaimer: Everything you see here is open and free to use as long as you comply with the [license](https://github.com/mirumee/saleor/blob/master/LICENSE). There are no hidden charges. We promise to do our best to fix bugs and improve the code.

Some situations do call for extra code; we can cover exotic use cases or build you a custom e-commerce appliance.

#### Crafted with ❤️ by [Mirumee Software](http://mirumee.com)

hello@mirumee.com
