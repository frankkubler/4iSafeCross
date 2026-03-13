#!/bin/bash
gpioset gpiochip2 15=1

# to copy in Bien sûr ! Voici comment créer un script qui s’exécute au démarrage pour activer le GPIO via la commande `gpioset` sur un Jetson Orin NX.

### 1. Créer le script`/usr/local/bin/set_poe_gpio.sh`


.