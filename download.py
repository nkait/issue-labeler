import sys
import os
import datetime
import argparse
from github import Github
from github.GithubException import GithubException
import pprint
import json
import logging
import time
from collections import defaultdict

parser = argparse.ArgumentParser(description='Download data for processing')
parser.add_argument('-user', type=str, help='username for github API')
parser.add_argument('-password', type=str, help='password for github API')
parser.add_argument('--test', dest='test', action='store_true', help='only run tests')

logging.basicConfig(level=logging.INFO, filename="download_log", filemode="a+",
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

class GithubAPIWrapper:
    def __init__(self, user, password):
        self.g = Github(user, password)

    def get_rate_limit(self):
        return self.g.get_rate_limit().rate.remaining

    def get_api_status(self):
        return self.g.get_api_status().status

    def query_by_stars(self, low, high):
        return self.g.search_repositories("stars:%d..%d" % (low, high))

class MockGithub:
    GITHUB_LIMIT = 1000

    def __init__(self):
        self.api_rate_limit = 300
        self.repositories = defaultdict(list)
        class MockRepo:
            def __init__(self, parent, raw_data):
                self.parent = parent
                self._raw_data = raw_data

            @property
            def raw_data(self):
                if self.parent.api_rate_limit <= 0:
                    raise Exception("Code shouldn't iterate when there are no more api calls")
                self.parent.api_rate_limit -= 1
                return self._raw_data

        for i in range(10100):
            for j in range(7):
                self.repositories[i].append(MockRepo(self, "%d/%d" % (i, j)))
        print "Done"

    def get_rate_limit(self):
        return self.api_rate_limit

    def get_api_status(self):
        return "OK"

    def get_repos(self, low, high):
        L = []
        for i in range(low, high+1):
            L += self.repositories[i]
        return L

    def get_raw_repos(self, low, high):
        L = self.get_repos(low, high)
        return [o._raw_data for o in L]

    def query_by_stars(self, low, high):
        if self.api_rate_limit == 0:
            raise Exception("API rate limit hit")
        self.api_rate_limit -= 1

        class QueryResult:
            def __init__(self, L, limit):
                self.L = L
                self.totalCount = len(L)
                self.limit = limit

            def __iter__(self):
                if len(self.L) > self.limit:
                    raise Exception("Code shouldn't iterate when there are more than %d results" % (self.limit,))
                return iter(self.L)

        return QueryResult(self.get_repos(low, high), self.GITHUB_LIMIT)

    def sleep(self, secs):
        self.api_rate_limit = 300

class Sleeper:
    def sleep(self, secs):
        time.sleep(secs)

class AppendStore:
    def __init__(self, file_path):
        self.f = open(file_path, "a+")

    def store(self, element):
        self.f.write(json.dumps(element)+"\n")

class OverwriteStore:
    def __init__(self, file_path):
        self.file_path = file_path

    def store(self, element):
        with open(self.file_path, "w") as f:
            f.write(json.dumps(element))

    def load(self):
        with open(self.file_path, "r") as f:
            return json.loads(f.read())

class MemoryStore:
    def __init__(self):
        self.L = []

    def store(self, element):
        self.L.append(element)

    def get_stored(self):
        return self.L

class RepoCollector:
    labels = ["enhancement", "bug", "feature", "question"]
    GITHUB_LIMIT = 1000
    API_THRESHOLD = 10
    WAIT_SECS = 600

    def wait_api(self):
        # TODO: watch out for separate rate limit for search and other
        while self.api.get_rate_limit() < self.API_THRESHOLD:
            logging.info("Waiting for %d seconds" % (self.WAIT_SECS))
            self.sleeper.sleep(self.WAIT_SECS)
        self.log_diag()

    def save_all(self, result):
        for elem in result:
            self.wait_api()
            self.store.store(elem.raw_data)

    def enqueue(self, low, high):
        self.queue.append((low, high))

    def enqueue_all(self, L):
        self.queue += L

    def dequeue(self):
        val = self.queue[0]
        self.queue = self.queue[1:]
        return val

    def save_queue(self):
        self.queue_store.store(self.queue)

    def load_queue(self):
        self.queue = self.queue_store.load()

    def execute_all(self):
        while len(self.queue) > 0:
            self.execute_once()

    def execute_once(self):
        low, high = self.dequeue()
        self.find_all(low, high)
        self.save_queue()

    def find_all(self, low, high):
        logging.info("Descending into: [%d, %d]" % (low, high))
        self.wait_api()
        query_result = self.api.query_by_stars(low, high)
        if query_result.totalCount <= self.GITHUB_LIMIT:
            self.save_all(query_result)
            return
        if low == high:
            logging.warn("Can not dissect further: %d stars has %d results" % (low, query_result.totalCount))
            return
        self.enqueue((high + low) / 2 + 1, high)
        self.enqueue(low, (high + low) / 2)

    def __init__(self, api, store, queue_store, sleeper = Sleeper()):
        self.api = api
        self.sleeper = sleeper
        self.store = store
        self.queue_store = queue_store
        self.repos = []
        self.queue = []

        #print "Title:"
        #pprint.pprint(issue.title)
        #print "User:"
        #pprint.pprint(issue.user.login)
        #print "Labels:"
        #for label in issue.labels:
        #    pprint.pprint(label.name)
        #print "Body:"
        #pprint.pprint(issue.body)
        #TODO: escape before saving/replace with spaces

        print self.api.query_by_stars(100, 1000).totalCount

        #for repo in self.g.search_repos():
        #    try:
        #        output.write(json.dumps(repo.raw_data) + "\n")
        #    except GithubException as ex:
        #        logging.exception("Exception received")

        #for repo in self.g.get_repos():
        #    try:
        #        output.write(json.dumps(repo.raw_data) + "\n")
        #    except GithubException as ex:
        #        logging.exception("Exception received")

        #for label in self.labels:
        #    for issue in g.search_issues("label:" + label + " comments:>0"):
        #        try:
        #            output.write(json.dumps(issue.raw_data) + "\n")
        #        except GithubException as ex:
        #            logging.exception("Exception received")
        self.log_diag()

    def log_diag(self):
        logging.info("API status: %s", self.api.get_api_status())
        logging.info("Current rate limit (QPH): %s", self.api.get_rate_limit())

def main(argv):
    args = parser.parse_args()

    if args.test:
        print "Testing"
        mg = MockGithub()
        ms = MemoryStore()
        qs = MemoryStore()
        rc = RepoCollector(mg, ms, qs, mg)
        rc.enqueue(10, 10000)
        rc.execute_all()
        result = ms.get_stored()
        expected = mg.get_raw_repos(10, 10000)
        if len(result) != len(expected):
            raise Exception("Length of result and expected differs")
        if set(result) != set(expected):
            raise Exception("Contents of result and expected differs")
        print "OK"
        return

    cur_time = datetime.datetime.now().isoformat()
    filename = "repos." + cur_time
    queuename = "queue"
    relpath = "collection/" + filename
    latestrelpath = "collection/repos.latest"

    if os.path.exists(latestrelpath):
        os.unlink(latestrelpath)
    os.symlink(filename, latestrelpath)
    gh = GithubAPIWrapper(args.user, args.password)
    if os.path.exists(queuename):
        rc = RepoCollector(gh, AppendStore(relpath), OverwriteStore(queuename))
        rc.load_queue()
    else:
        rc = RepoCollector(gh, AppendStore(relpath), OverwriteStore(queuename))
        rc.enqueue(100, 100000)
    rc.execute_all()

if __name__ == "__main__":
    main(sys.argv)
