#!/bin/bash
# Alimentation PoE du reServer J4012 : maintient la ligne "PSE_PWR_EN"
# (gpiochip2, ligne 15) a l'etat haut.
#
# En exploitation, c'est set-poe-gpio.service qui fait ce travail au boot.
# Ce script sert au test manuel : il ne rend pas la main, et Ctrl+C coupe
# l'alimentation des cameras.
#
# --mode=signal est obligatoire : sans lui gpioset se termine, le kernel
# relache la ligne et le PSE n'alimente plus aucun port.
set -euo pipefail

exec gpioset --mode=signal gpiochip2 15=1
