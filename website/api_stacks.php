<?php

require __DIR__ . '/vendor/autoload.php';

use NextcloudDeckWorkflows\ApiBadRequestException;
use NextcloudDeckWorkflows\ApiEndpoint;
use NextcloudDeckWorkflows\NextcloudApi;

ApiEndpoint::run(function (NextcloudApi $api) {
    $boardId = (int) ($_GET['board_id'] ?? 0);
    if ($boardId <= 0) {
        throw new ApiBadRequestException('Missing or unknown board_id');
    }
    return ['stacks' => $api->listStacks($boardId)];
});
