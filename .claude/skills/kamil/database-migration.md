<!-- Installed from SkillHound: wshobson/agents -->
---
name: database-migration
description: Execute database migrations across ORMs and platforms with zero-downtime strategies, data transformation, and rollback procedures. Use when migrating databases, changing schemas, performing data transformations, or implementing zero-downtime deployment strategies.
---

# Database Migration

Master database schema and data migrations across ORMs (Sequelize, TypeORM, Prisma), including rollback strategies and zero-downtime deployments.

## When to Use This Skill

- Migrating between different ORMs
- Performing schema transformations
- Moving data between databases
- Implementing rollback procedures
- Zero-downtime deployments
- Database version upgrades
- Data model refactoring

## ORM Migrations

### Sequelize Migrations

```javascript
// migrations/20231201-create-users.js
module.exports = {
  up: async (queryInterface, Sequelize) => {
    await queryInterface.createTable("users", {
      id: { type: Sequelize.INTEGER, primaryKey: true, autoIncrement: true },
      email: { type: Sequelize.STRING, unique: true, allowNull: false },
      createdAt: Sequelize.DATE,
      updatedAt: Sequelize.DATE,
    });
  },
  down: async (queryInterface) => {
    await queryInterface.dropTable("users");
  },
};

// Run: npx sequelize-cli db:migrate
// Rollback: npx sequelize-cli db:migrate:undo
```

### TypeORM Migrations

```typescript
// migrations/1701234567-CreateUsers.ts
import { MigrationInterface, QueryRunner, Table } from "typeorm";

export class CreateUsers1701234567 implements MigrationInterface {
  public async up(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.createTable(new Table({
      name: "users",
      columns: [
        { name: "id", type: "int", isPrimary: true, isGenerated: true, generationStrategy: "increment" },
        { name: "email", type: "varchar", isUnique: true },
        { name: "created_at", type: "timestamp", default: "CURRENT_TIMESTAMP" },
      ],
    }));
  }
  public async down(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.dropTable("users");
  }
}

// Run: npm run typeorm migration:run
// Rollback: npm run typeorm migration:revert
```

### Prisma Migrations

```prisma
model User {
  id        Int      @id @default(autoincrement())
  email     String   @unique
  createdAt DateTime @default(now())
}
// Generate: npx prisma migrate dev --name create_users
// Apply:    npx prisma migrate deploy
```

## Schema Transformations

### Adding Columns with Defaults

Always supply a `defaultValue` and `allowNull: false` together to avoid NULL constraint errors on existing rows.

### Renaming Columns (Zero Downtime — 3-step)

1. Add new column, copy data from old column.
2. Deploy application code that reads/writes the new column.
3. Drop old column in a follow-up migration.

### Changing Column Types

For large tables use a multi-step approach: add new column → copy+transform data → drop old column → rename new column. Never use `changeColumn` directly on large tables in production.

## Data Transformations

### Complex Data Migration Pattern

```javascript
module.exports = {
  up: async (queryInterface) => {
    const [rows] = await queryInterface.sequelize.query(
      "SELECT id, address_string FROM users"
    );
    for (const row of rows) {
      const [street, city, state] = row.address_string.split(",").map(s => s?.trim());
      await queryInterface.sequelize.query(
        "UPDATE users SET street=:street, city=:city, state=:state WHERE id=:id",
        { replacements: { id: row.id, street, city, state } }
      );
    }
    await queryInterface.removeColumn("users", "address_string");
  },
  down: async (queryInterface, Sequelize) => {
    await queryInterface.addColumn("users", "address_string", { type: Sequelize.STRING });
    await queryInterface.sequelize.query(
      "UPDATE users SET address_string = CONCAT(street, ', ', city, ', ', state)"
    );
    for (const col of ["street", "city", "state"]) {
      await queryInterface.removeColumn("users", col);
    }
  },
};
```

## Rollback Strategies

### Transaction-Based Migrations

Wrap all DDL + DML in a single transaction. On error, rollback and rethrow.

```javascript
module.exports = {
  up: async (queryInterface, Sequelize) => {
    const t = await queryInterface.sequelize.transaction();
    try {
      await queryInterface.addColumn("users", "verified",
        { type: Sequelize.BOOLEAN, defaultValue: false }, { transaction: t });
      await queryInterface.sequelize.query(
        "UPDATE users SET verified = true WHERE email_verified_at IS NOT NULL",
        { transaction: t }
      );
      await t.commit();
    } catch (err) {
      await t.rollback();
      throw err;
    }
  },
  down: async (queryInterface) => {
    await queryInterface.removeColumn("users", "verified");
  },
};
```

### Checkpoint-Based Rollback

For destructive migrations on large tables: create a backup table before starting, verify row counts after, drop backup on success, restore from backup on failure.

## Zero-Downtime Deployment Rules

1. **Never drop columns in the same deploy as the code change** — deploy code first, drop column next deploy.
2. **Never add NOT NULL columns without a default** — existing rows will fail constraint.
3. **Use `CREATE INDEX CONCURRENTLY`** (Postgres) to avoid table locks.
4. **Batch large UPDATE statements** — never update millions of rows in one statement.
5. **Test rollback on staging** before every production migration.

## Django-Specific Notes (taleemabad-core)

```bash
# Generate migration
python manage.py makemigrations <app>

# Apply
python manage.py migrate

# Rollback to specific migration
python manage.py migrate <app> <migration_name>

# Show migration plan
python manage.py showmigrations
```

- Use `migrations.RunSQL` with `reverse_sql` for raw SQL migrations.
- Use `migrations.RunPython` with an `atomic=False` kwarg for non-transactional operations (e.g., Postgres `CREATE INDEX CONCURRENTLY`).
- Always write a `reverse` function for `RunPython` so rollback works.
