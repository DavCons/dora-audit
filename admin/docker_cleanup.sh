docker ps -aq | xargs -r docker stop
docker container prune -f
docker image prune -a -f
docker volume prune -f
docker builder prune -a -f
sudo apt-get clean
