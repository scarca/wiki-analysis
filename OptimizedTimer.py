import multiprocessing as mp
import queue
import time
import logging
import atexit
from neo4j.v1 import GraphDatabase, basic_auth
import neo4j.exceptions
#We're going to do this in the same we do the MultiThreading so that its easier
logging.basicConfig(level=logging.WARNING, format='(%(processName)s: %(asctime)s) %(message)s',)

class CreateNode(mp.Process):
    def __init__(self, q, name="CreateNode"):
        self.q = q
        self.session_count = 0
        self.driver = GraphDatabase.driver("bolt://localhost:7687", auth=basic_auth("neo4j", "neo4J"))
        self.session = self.driver.session()
        super(CreateNode, self).__init__(name=name)
    def run(self):
        empty_count = 0
        m_queue = self.q
        while empty_count <= 5:
            title, ft, ID = None, None, None
            try:
                (title, ft, ID) = m_queue.get(block=True, timeout=1)
            except queue.Empty:
                empty_count += 1
                logging.warning("Empty Queue Count" + str(empty_count))
            else:
                successful = False
                try:
                    if ft == 0:
                        self.session.run("CREATE (a:article {title: {title}, id:{id}})", {"title": title, "id": ID})
                        self.session_count += 1
                    elif ft == 6:
                        self.session.run("CREATE (a:file {title: {title}, id:{id}})", {"title": title, "id": ID})
                        self.session_count += 1
                    else:
                        pass
                except:
                    pass
                else:
                    successful = True
            if self.session_count > 100000:
                self.session.close()
                self.session = self.driver.session()
                self.session_count = 0


class TitleExtractor(mp.Process):
    def __init__(self, queue, name=None):
        self.queue = queue
        super(TitleExtractor, self).__init__(name=name)
    def run(self):
        queue = self.queue
        inPage = False
        with open('enwiki-20170420-pages-articles.xml', 'r') as wiki:
            c = 1
            pc = 0
            title = ""
            ft = None
            ID = None
            isRedirect = None
            for line in wiki:
                line = line.strip()
                if line == '</page>':
                    inPage = False
                    c += 1
                    if not isRedirect:
                        queue.put((title, ft, ID))
                elif inPage:
                    if pc == 1:
                        #Grab Title
                        title = line[7:-8].lower()
                        pc += 1
                    elif pc == 2:
                        #Figure out namespace
                        ft = int(line[4:-5])
                        pc += 1
                    elif pc == 3:
                        ID = int(line[4:-5])
                        pc += 1
                    elif pc == 4:
                        if line[0:9] == "<redirect":
                            isRedirect = True
                elif line == '<page>':
                    inPage = True
                    isRedirect=False
                    pc = 1

if __name__ == "__main__":
    startTime = time.time()
    manager = mp.Manager()
    q = manager.Queue(100000)
    t = TitleExtractor(q)
    n = CreateNode(q)
    def closer(q):
        t.terminate()
        n.terminate()
        del q
    atexit.register(closer, q)
    t.start()
    time.sleep(1)
    n.start()
    t.join()
    logging.warning("Finished title extraction")
    n.join()
    endTime = time.time()
    logging.warning("Finished")
    with open('TitleExtractorTimer.txt', 'w') as of:
        of.write(str(endTime - startTime))
        of.flush()
