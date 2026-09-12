CREATE TABLE index_revisions (
    root_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL
);
INSERT INTO index_revisions(root_id, revision)
SELECT id, 1 FROM objects WHERE kind='index';

CREATE TRIGGER index_revision_insert AFTER INSERT ON objects
WHEN NEW.kind='index'
BEGIN
    INSERT INTO index_revisions(root_id, revision) VALUES(NEW.id, 1)
    ON CONFLICT(root_id) DO UPDATE SET revision=revision+1;
END;

CREATE TRIGGER index_revision_update AFTER UPDATE ON objects
WHEN OLD.kind='index' OR NEW.kind='index'
BEGIN
    INSERT INTO index_revisions(root_id, revision)
    SELECT OLD.id, 1 WHERE OLD.kind='index'
    ON CONFLICT(root_id) DO UPDATE SET revision=revision+1;
    INSERT INTO index_revisions(root_id, revision)
    SELECT NEW.id, 1 WHERE NEW.kind='index' AND (OLD.kind!='index' OR OLD.id!=NEW.id)
    ON CONFLICT(root_id) DO UPDATE SET revision=revision+1;
END;

CREATE TRIGGER index_revision_delete AFTER DELETE ON objects
WHEN OLD.kind='index'
BEGIN
    INSERT INTO index_revisions(root_id, revision) VALUES(OLD.id, 1)
    ON CONFLICT(root_id) DO UPDATE SET revision=revision+1;
END;
