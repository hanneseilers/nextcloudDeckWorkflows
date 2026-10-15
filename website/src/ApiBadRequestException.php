<?php

namespace NextcloudDeckWorkflows;

/**
 * Thrown by an ApiEndpoint::run() callback for a client-side problem (missing
 * or invalid query parameter) - caught separately from a general \Throwable
 * so it becomes an HTTP 400, not the 502 an unreachable Nextcloud gets.
 */
class ApiBadRequestException extends \RuntimeException
{
}
