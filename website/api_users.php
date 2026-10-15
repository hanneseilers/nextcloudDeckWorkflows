<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\ApiEndpoint;
use NextcloudDeckWorkflows\NextcloudApi;

ApiEndpoint::run(function (NextcloudApi $api) {
    $query = trim((string) ($_GET['query'] ?? ''));

    // Mirrors the builder's own 3-character throttle - also enforced here so a
    // request bypassing the browser can't trigger a (likely huge) unfiltered
    // user listing.
    if (mb_strlen($query) < 3) {
        return ['users' => []];
    }

    return ['users' => $api->searchUsers($query)];
});
