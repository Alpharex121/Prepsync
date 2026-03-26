import json


class FakeRedis:
    def __init__(self):
        self.kv = {}
        self.hashes = {}
        self.lists = {}
        self.zsets = {}

    async def set(self, key, value):
        self.kv[key] = str(value)

    async def get(self, key):
        return self.kv.get(key)

    async def hset(self, key, mapping):
        h = self.hashes.setdefault(key, {})
        for k, v in mapping.items():
            h[str(k)] = str(v)

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    async def delete(self, key):
        self.kv.pop(key, None)
        self.hashes.pop(key, None)
        self.lists.pop(key, None)
        self.zsets.pop(key, None)

    async def rpush(self, key, *values):
        lst = self.lists.setdefault(key, [])
        lst.extend([str(v) for v in values])

    async def llen(self, key):
        return len(self.lists.get(key, []))

    async def lindex(self, key, index):
        lst = self.lists.get(key, [])
        if index < 0 or index >= len(lst):
            return None
        return lst[index]

    async def lrange(self, key, start, end):
        lst = self.lists.get(key, [])
        if end == -1:
            return lst[start:]
        return lst[start : end + 1]

    async def zadd(self, key, mapping):
        z = self.zsets.setdefault(key, {})
        for member, score in mapping.items():
            z[str(member)] = float(score)

    async def zrem(self, key, member):
        z = self.zsets.setdefault(key, {})
        z.pop(str(member), None)

    async def zincrby(self, key, delta, member):
        z = self.zsets.setdefault(key, {})
        member = str(member)
        z[member] = float(z.get(member, 0.0)) + float(delta)
        return z[member]

    async def zrevrange(self, key, start, end, withscores=False):
        z = self.zsets.get(key, {})
        ordered = sorted(z.items(), key=lambda item: item[1], reverse=True)
        if end == -1:
            sliced = ordered[start:]
        else:
            sliced = ordered[start : end + 1]
        if withscores:
            return sliced
        return [member for member, _ in sliced]


def dump_json(data):
    return json.dumps(data)

