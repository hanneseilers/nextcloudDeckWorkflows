<?php

// The project root itself has no pages - the website lives in website/.
// Relative, so this works no matter which (sub)directory the project is in.
header('Location: website/', true, 302);
