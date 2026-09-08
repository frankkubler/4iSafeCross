#!/bin/bash
# Alimentation PoE du reServer J4012 : maintient la ligne "PSE_PWR_EN"
# (gpiochip2, ligne 15) a l'etat haut.
#
# En exploitation, c'est set-poe-gpio.service qui fait ce travail au boot.
# Ce script sert au test manuel : il ne rend pas la main, et Ctrl+C coupe
# l'alimentation des cameras.
#
# --mode=signal : le process tient la ligne. Sans lui gpioset se termine et
# la ligne est relachee ; le pilote pca953x la laisse haute en pratique, mais
# libgpiod qualifie cet etat de non defini, on ne s'y fie pas.
set -euo pipefail

exec gpioset --mode=signal gpiochip2 15=1
