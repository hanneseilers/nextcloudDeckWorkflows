<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\ApiEndpoint;
use NextcloudDeckWorkflows\NextcloudApi;

ApiEndpoint::run(fn (NextcloudApi $api) => ['calendars' => $api->listCalendars()]);
