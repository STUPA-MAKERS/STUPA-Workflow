---
id: "002150"
title: Every answer of the server carries the app version
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/core/pwa/app-version.service.spec.ts:AppVersionService"
implementation:
  - deploy/web/Dockerfile
  - deploy/web/nginx.conf
  - frontend/src/app/core/pwa/build-id.ts
scope:
  - deploy/web
  - frontend/src/app/core/pwa
---

# Every answer of the server carries the app version

Every HTTP answer of the web server must carry the header `X-App-Version`, also an error
answer of the API. The value must be the build ID of the frontend that the server serves. The
build ID must be a hash of the frontend sources, and the same build ID must be in the
frontend bundle.

Reason: The API and the frontend are two images, and a deploy restarts only the changed
images. Only the build ID of the served frontend tells that a browser runs an old frontend.
A deploy that changes only the backend must not reload a browser. nginx in the web image
sets the header, because only that image knows the frontend build.

Test: A unit test answers an API request with `X-App-Version` and checks that the app reads
it. The image build fails when the build ID is not in the bundle.
